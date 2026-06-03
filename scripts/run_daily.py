#!/usr/bin/env python3
"""AI Radar — Daily digest orchestrator (OpenRouter + DeepSeek V4 Flash).

Zero dependencies on Claude Code CLI. Uses OpenClaw's stored credentials
(OPENROUTER_API_KEY from ~/.openclaw/.env, Discord bot token from openclaw.json)
to run the full pipeline:
  1. Fetch sources
  2. Call OpenRouter / DeepSeek V4 Flash to generate HTML
  3. Write to docs/
  4. git commit + push (GitHub Pages auto-builds)
  5. Wait for build
  6. Discord post with link + .html attachment

Usage:
  python3 run_daily.py              # normal run, today
  python3 run_daily.py --test       # writes to *-test.html, doesn't overwrite index
  python3 run_daily.py --no-discord # skip Discord post
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

# ────────────────────────── paths and config ──────────────────────────
RADAR = Path.home() / "ai-radar"
PROMPT_FILE = RADAR / "prompts" / "digest.md"
OUTPUT_DIR = RADAR / "docs"
OUTPUT_RAW_DIR = RADAR / "output"
ARCHIVE_FILE = OUTPUT_DIR / "archive.json"
LOG_DIR = RADAR / "logs"

OPENCLAW_ENV = Path.home() / ".openclaw" / ".env"
OPENCLAW_CONFIG = Path.home() / ".openclaw" / "openclaw.json"
CLAUDE_DISCORD_ENV = Path.home() / ".claude" / "channels" / "discord" / ".env"

DISCORD_CHANNEL_ID = "1484904539952775351"
GITHUB_PAGES_URL = "https://ethan-m25.github.io/ai-radar/"
MODEL = "deepseek/deepseek-v4-flash"

# Sources to fetch. Keep this list source-heavy and primary-source biased; the
# prompt still applies the hard cap and exclusion rules so coverage expansion
# does not turn the digest into a recap newsletter.
SOURCES = {
    "smol_ai": {
        "url": "https://news.smol.ai/issues/",
        "label": "news.smol.ai/issues/ (AINews aggregation)",
        "max_chars": 18000,
    },
    "hackernews": {
        "url": "https://news.ycombinator.com",
        "label": "news.ycombinator.com front page",
        "max_chars": 10000,
    },
    "ossinsight": {
        "url": "https://ossinsight.io/trending/ai",
        "label": "ossinsight.io/trending/ai (28-day GitHub momentum)",
        "max_chars": 8000,
    },
    "github_trending": {
        "url": "https://github.com/trending?since=daily",
        "label": "github.com/trending daily (raw repo breakout scan)",
        "max_chars": 9000,
    },
    "openai": {
        "url": "https://openai.com/news/rss",
        "label": "openai.com/news/rss (official ships)",
        "max_chars": 10000,
    },
    "openai_developers": {
        "url": "https://developers.openai.com/rss.xml",
        "label": "developers.openai.com/rss.xml (developer/API releases)",
        "max_chars": 12000,
    },
    "anthropic": {
        "url": "https://www.anthropic.com/news",
        "label": "anthropic.com/news (official ships)",
        "max_chars": 9000,
    },
    "google_deepmind": {
        "url": "https://deepmind.google/blog/",
        "label": "deepmind.google/blog (Google DeepMind official)",
        "max_chars": 9000,
    },
    "huggingface_blog": {
        "url": "https://huggingface.co/blog",
        "label": "huggingface.co/blog (open model/tool releases)",
        "max_chars": 8000,
    },
    "huggingface_models": {
        "url": "https://huggingface.co/models?sort=trending",
        "label": "huggingface.co/models trending",
        "max_chars": 6000,
    },
    "mistral": {
        "url": "https://mistral.ai/news/",
        "label": "mistral.ai/news (official ships)",
        "max_chars": 8000,
    },
    "simonw": {
        "url": "https://simonwillison.net/tags/ai/",
        "label": "simonwillison.net/tags/ai (practitioner/KOL signal)",
        "max_chars": 8000,
    },
}

LANGS = {
    "zh": {
        "name": "Chinese",
        "html_lang": "zh-Hans",
        "site_dir": OUTPUT_DIR,
        "raw_dir": OUTPUT_RAW_DIR,
        "archive_file": ARCHIVE_FILE,
        "base_url": GITHUB_PAGES_URL,
        "archive_title": "所有过往日报与周报",
        "archive_lead": "回看你可能错过的，或想再读一遍的——按周分组，最新在上。每条带 tier 分布。",
        "today_label": "今日",
        "archive_label": "归档",
        "weekly_prefix": "📅 周报 · ",
    },
    "en": {
        "name": "English",
        "html_lang": "en",
        "site_dir": OUTPUT_DIR / "en",
        "raw_dir": OUTPUT_RAW_DIR / "en",
        "archive_file": OUTPUT_DIR / "en" / "archive.json",
        "base_url": GITHUB_PAGES_URL + "en/",
        "archive_title": "All Daily and Weekly Issues",
        "archive_lead": "A standalone English archive of AI Radar issues, grouped by week with the same signal tiers as the Chinese site.",
        "today_label": "Today",
        "archive_label": "Archive",
        "weekly_prefix": "📅 Weekly · ",
    },
}

# ────────────────────────── helpers ──────────────────────────

def log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def _parse_env_file(path: Path) -> dict:
    out = {}
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def load_secrets() -> dict:
    secrets = {}

    # OpenRouter API key — from OpenClaw's .env
    secrets.update(_parse_env_file(OPENCLAW_ENV))

    # Discord bot token — prefer Claude Code's MCP bot (Clawii-CC), which has
    # cc-workspace channel access. Fall back to OpenClaw's bot if not present.
    claude_env = _parse_env_file(CLAUDE_DISCORD_ENV)
    if claude_env.get("DISCORD_BOT_TOKEN"):
        secrets["DISCORD_BOT_TOKEN"] = claude_env["DISCORD_BOT_TOKEN"]
        secrets["DISCORD_BOT_SOURCE"] = "claude-code-mcp (Clawii-CC)"
    elif OPENCLAW_CONFIG.exists():
        cfg = json.loads(OPENCLAW_CONFIG.read_text())
        tok = cfg.get("channels", {}).get("discord", {}).get("token", "")
        if tok:
            secrets["DISCORD_BOT_TOKEN"] = tok
            secrets["DISCORD_BOT_SOURCE"] = "openclaw (Clawii)"

    missing = [k for k in ("OPENROUTER_API_KEY", "DISCORD_BOT_TOKEN") if not secrets.get(k)]
    if missing:
        log(f"❌ missing secrets: {missing}")
        sys.exit(2)
    return secrets


def http_get(url: str, *, timeout: int = 25) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 AI-Radar/1.0",
            "Accept": "text/html,application/json,*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def strip_html(s: str, max_chars: int = 25000) -> str:
    """Crude HTML-to-text — good enough to feed to LLM."""
    import re
    s = re.sub(r"<script[^>]*>.*?</script>", " ", s, flags=re.S | re.I)
    s = re.sub(r"<style[^>]*>.*?</style>", " ", s, flags=re.S | re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"&nbsp;", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:max_chars]


def fetch_sources() -> dict:
    out = {}
    for name, cfg in SOURCES.items():
        url = cfg["url"]
        log(f"  fetch {name}: {url}")
        try:
            raw = http_get(url)
            out[name] = strip_html(raw)
            log(f"    → {len(out[name])} chars")
        except Exception as e:
            out[name] = f"[fetch failed: {type(e).__name__}: {e}]"
            log(f"    ⚠️ {e}")
    return out


def find_latest_html_template(site_dir: Path = OUTPUT_DIR) -> Path | None:
    """Use most recent docs/*.html (NOT index.html) as a structural reference."""
    candidates = sorted(
        [p for p in site_dir.glob("2026-*.html") if "-test" not in p.stem],
        reverse=True,
    )
    return candidates[0] if candidates else None


def extract_history(n_days: int = 7, exclude_date: str | None = None,
                    site_dir: Path = OUTPUT_DIR) -> dict:
    """Read past N days of dated daily HTML and pull out feature + killed lists.

    Returns:
        {
          "featured": [
            {"date": "2026-05-25", "tier": "crit", "title": "..."},
            ...
          ],
          "killed": [
            {"date": "2026-05-25", "source": "HN", "topic": "...", "reason": "..."},
            ...
          ],
        }
    """
    from datetime import datetime as _dt, timedelta as _td
    import re

    today_dt = _dt.now()
    featured: list = []
    killed: list = []
    days_scanned: list = []

    for i in range(1, n_days + 1):
        d = today_dt - _td(days=i)
        date_str = d.strftime("%Y-%m-%d")
        if exclude_date and date_str == exclude_date:
            continue
        path = site_dir / f"{date_str}.html"
        if not path.exists():
            continue
        days_scanned.append(date_str)
        html = path.read_text()

        # Featured items: <article id="..." class="item item--TIER">...<h2 class="display title">TITLE</h2>
        article_pat = re.compile(
            r'<article\s+id="([^"]+)"\s+class="item\s+item--(crit|look|fyi)"\s*>(.*?)</article>',
            re.S,
        )
        title_pat = re.compile(r'<h2\s+class="display\s+title"[^>]*>(.*?)</h2>', re.S)
        for m in article_pat.finditer(html):
            iid, tier, body = m.group(1), m.group(2), m.group(3)
            tm = title_pat.search(body)
            if not tm:
                continue
            title = re.sub(r"<[^>]+>", "", tm.group(1)).strip()
            featured.append({
                "date": date_str,
                "tier": tier,
                "id": iid,
                "title": title,
            })

        # Killed list: rows in <section class="killed">...<tbody>...<tr><td>...</td>...</tr>
        killed_section = re.search(r'<section\s+class="killed">.*?</section>', html, re.S)
        if killed_section:
            row_pat = re.compile(
                r"<tr>\s*<td>(.*?)</td>\s*<td>(.*?)</td>\s*<td>(.*?)</td>\s*</tr>",
                re.S,
            )
            for row in row_pat.finditer(killed_section.group(0)):
                cells = [re.sub(r"<[^>]+>", "", c).strip() for c in row.groups()]
                if len(cells) == 3 and cells[1] and cells[1] != "—":
                    killed.append({
                        "date": date_str,
                        "source": cells[0],
                        "topic": cells[1],
                        "reason": cells[2],
                    })

    log(f"  history: scanned {len(days_scanned)} days ({days_scanned}), "
        f"found {len(featured)} featured + {len(killed)} killed entries")
    return {"featured": featured, "killed": killed, "days_scanned": days_scanned}


def format_history_for_prompt(history: dict) -> str:
    if not history["days_scanned"]:
        return "(no prior digests in past 7 days — this is the first issue)"

    out = ["**Past 7 days summary**:", ""]
    out.append(f"_Scanned dates: {', '.join(history['days_scanned'])}_")
    out.append("")

    # Group featured by date
    by_date: dict = {}
    for f in history["featured"]:
        by_date.setdefault(f["date"], []).append(f)

    if by_date:
        out.append("### Previously featured (apply SUPPRESSION rule — these cannot occupy top-3 today unless a trigger event occurred):")
        for date in sorted(by_date.keys(), reverse=True):
            tier_emoji = {"crit": "🚨", "look": "👀", "fyi": "ℹ️"}
            days_ago = (datetime.now() - datetime.strptime(date, "%Y-%m-%d")).days
            day_marker = f"Day {days_ago}"
            for f in by_date[date]:
                emoji = tier_emoji.get(f["tier"], "?")
                out.append(f"- {day_marker} ({date}): {emoji} {f['title']}")
        out.append("")

    if history["killed"]:
        # Group killed by topic to dedupe
        killed_by_topic: dict = {}
        for k in history["killed"]:
            key = k["topic"]
            if key not in killed_by_topic:
                killed_by_topic[key] = {"first_seen": k["date"], "sources": set(), "reasons": set()}
            killed_by_topic[key]["sources"].add(k["source"])
            killed_by_topic[key]["reasons"].add(k["reason"])

        out.append("### Previously KILLED (apply RE-EVALUATION rule — actively check today if signal has grown enough to PROMOTE to top-3):")
        for topic, info in killed_by_topic.items():
            srcs = ", ".join(sorted(info["sources"]))
            out.append(f"- ({info['first_seen']}) {topic}  _[from {srcs}; previously skipped because: {next(iter(info['reasons']))}]_")
        out.append("")

    return "\n".join(out)


def call_openrouter(secrets: dict, system: str, user: str) -> tuple[str, dict]:
    body = json.dumps({
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.4,
        "max_tokens": 32000,
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {secrets['OPENROUTER_API_KEY']}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/ethan-m25/ai-radar",
            "X-Title": "AI Radar",
        },
    )
    log(f"  → OpenRouter ({MODEL}) — sending {len(body)} bytes...")
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body_resp = e.read().decode("utf-8", errors="replace")
        log(f"❌ OpenRouter HTTP {e.code}: {body_resp[:500]}")
        raise

    if "choices" not in data or not data["choices"]:
        log(f"❌ OpenRouter no choices: {data}")
        raise RuntimeError("OpenRouter returned no choices")

    content = data["choices"][0]["message"]["content"]
    usage = data.get("usage", {})
    log(f"  ← {len(content)} chars · usage {usage}")
    return content, usage


def extract_html(text: str) -> str:
    """Pull <!doctype...> ... </html> out of a possibly-fenced response."""
    import re
    # If it's wrapped in ```html ... ``` strip the fences
    m = re.search(r"```(?:html)?\s*(.*?)```", text, re.S | re.I)
    if m:
        text = m.group(1)
    # Find the doctype to closing html
    m = re.search(r"(<!doctype[^>]*>.*?</html\s*>)", text, re.S | re.I)
    if m:
        return m.group(1).strip()
    # Fallback: assume whole text is the HTML
    return text.strip()


def update_archive_json(archive_file: Path, today: str, weekday: str, week: int,
                        headline: str, summary: str, counts: dict,
                        filename: str) -> int:
    if archive_file.exists():
        data = json.loads(archive_file.read_text())
    else:
        data = {
            "$schema": "https://github.com/ethan-m25/ai-radar",
            "description": "AI Radar — chronological list of all published digests.",
            "issues": [],
        }

    issues = data.get("issues", [])
    # Skip duplicates by date+kind
    issues = [i for i in issues if not (i.get("date") == today and i.get("kind") == "daily")]

    # Compute new issue number
    daily_count = sum(1 for i in issues if i.get("kind") == "daily")
    issue_num = daily_count + 1

    new_entry = {
        "date": today,
        "weekday": weekday,
        "week": week,
        "issue": issue_num,
        "kind": "daily",
        "headline": headline,
        "summary": summary,
        "counts": counts,
        "url": filename,
    }
    # Most recent first
    issues.insert(0, new_entry)
    data["issues"] = issues
    archive_file.parent.mkdir(parents=True, exist_ok=True)
    archive_file.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    log(f"  updated {archive_file.relative_to(RADAR)}: issue #{issue_num}")
    return issue_num


def sync_archive_json(source: Path, target: Path, entry: dict) -> None:
    """Maintain a separate language archive with one translated/current entry."""
    if target.exists():
        data = json.loads(target.read_text())
    elif source.exists():
        data = json.loads(source.read_text())
    else:
        data = {
            "$schema": "https://github.com/ethan-m25/ai-radar",
            "description": "AI Radar — chronological list of all published digests.",
            "issues": [],
        }

    issues = data.get("issues", [])
    issues = [i for i in issues if not (i.get("date") == entry["date"] and i.get("kind") == entry["kind"])]
    issues.insert(0, entry)

    def sort_key(i):
        kind_rank = 1 if i.get("kind") == "weekly" else 0
        return (i.get("date", ""), kind_rank)

    data["issues"] = sorted(issues, key=sort_key, reverse=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    log(f"  synced {target.relative_to(RADAR)}")


def write_archive_page(lang: str) -> None:
    cfg = LANGS[lang]
    site_dir = cfg["site_dir"]
    site_dir.mkdir(parents=True, exist_ok=True)
    weekly_prefix = cfg["weekly_prefix"]
    empty_text = "还没有归档内容。明天早 07:07 见。" if lang == "zh" else "No archive entries yet. Check back after the next run."
    failed_text = "加载归档失败" if lang == "zh" else "Failed to load archive"
    footer = "每天 07:07 自动更新 · 每周日 08:00 出周报。" if lang == "zh" else "Daily at 07:07 · Weekly wrap on Sunday at 08:00."
    find_hint = "想搜某条历史信号？在浏览器里" if lang == "zh" else "Looking for a past signal? Use your browser's"
    today_label = cfg["today_label"]
    archive_label = cfg["archive_label"]

    html = f"""<!doctype html>
<html lang="{cfg['html_lang']}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#f4ede0">
<title>AI Radar · {archive_label}</title>
<meta name="description" content="AI Radar archive">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght,SOFT@0,9..144,300..900,0..100;1,9..144,300..900,0..100&family=Geist:wght@300..700&family=Geist+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root {{ --bg: oklch(0.97 0.012 85); --bg-card: oklch(0.99 0.008 85); --ink: oklch(0.18 0.025 270); --ink-soft: oklch(0.36 0.020 270); --ink-mute: oklch(0.52 0.014 270); --hairline: oklch(0.86 0.015 85); --hairline-bold: oklch(0.72 0.020 85); --tier-crit: oklch(0.55 0.22 26); --tier-look: oklch(0.68 0.16 70); --tier-fyi: oklch(0.55 0.03 250); --t-cover: clamp(2.5rem, 7vw, 4rem); --t-h3: clamp(1.05rem, 2.2vw, 1.2rem); --t-body: clamp(1rem, 1.7vw, 1.0625rem); --t-small: 0.875rem; --t-micro: 0.75rem; }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: var(--bg); color: var(--ink); font-family: 'Geist', -apple-system, BlinkMacSystemFont, sans-serif; font-size: var(--t-body); line-height: 1.6; -webkit-font-smoothing: antialiased; }}
  .display {{ font-family: 'Fraunces', serif; font-variation-settings: "SOFT" 30, "opsz" 144; font-weight: 500; letter-spacing: 0; line-height: 1.05; }}
  .display-italic {{ font-family: 'Fraunces', serif; font-style: italic; font-variation-settings: "SOFT" 60, "opsz" 144; }}
  .mono {{ font-family: 'Geist Mono', monospace; font-size: 0.92em; }}
  .smallcaps {{ text-transform: uppercase; letter-spacing: 0.12em; font-size: var(--t-micro); font-weight: 500; color: var(--ink-mute); }}
  .page {{ max-width: 780px; margin: 0 auto; padding: 1.5rem 1.25rem 4rem; }}
  @media (min-width: 768px) {{ .page {{ padding: 3rem 2rem 6rem; }} }}
  .masthead {{ display: flex; align-items: baseline; justify-content: space-between; padding-bottom: 1rem; border-bottom: 1px solid var(--hairline-bold); margin-bottom: 2.5rem; }}
  .masthead .logo {{ font-family: 'Fraunces', serif; font-weight: 700; font-size: 1.1rem; letter-spacing: 0.02em; color: var(--ink); text-decoration: none; }}
  .masthead .nav {{ display: flex; gap: 1.2rem; }}
  .masthead .nav a {{ font-size: var(--t-micro); color: var(--ink-mute); letter-spacing: 0.08em; text-transform: uppercase; text-decoration: none; border-bottom: 1px solid transparent; }}
  .masthead .nav a:hover, .masthead .nav a.current {{ color: var(--ink); border-bottom-color: var(--ink); }}
  .cover {{ margin-bottom: 3rem; }}
  .cover .kicker {{ display: block; margin-bottom: 1.25rem; }}
  .cover h1 {{ font-size: var(--t-cover); margin: 0; max-width: 18ch; }}
  .cover .lead {{ font-family: 'Fraunces', serif; font-style: italic; font-size: var(--t-h3); color: var(--ink-soft); max-width: 50ch; margin: 1.25rem 0 0; }}
  .issues-list {{ margin-top: 1rem; border-top: 1px solid var(--hairline-bold); }}
  .week-group {{ border-bottom: 1px solid var(--hairline-bold); padding: 2rem 0 0.5rem; }}
  .week-label {{ font-family: 'Geist Mono', monospace; font-size: var(--t-micro); text-transform: uppercase; letter-spacing: 0.12em; color: var(--ink-mute); margin-bottom: 1rem; }}
  .issue-card {{ display: grid; grid-template-columns: 4rem 1fr auto; gap: 1rem; align-items: baseline; padding: 1rem 0; border-top: 1px solid var(--hairline); color: var(--ink); text-decoration: none; }}
  .issue-card:hover {{ background: var(--bg-card); }}
  .issue-card .date {{ font-family: 'Geist Mono', monospace; font-size: var(--t-small); color: var(--ink-soft); font-variant-numeric: tabular-nums; }}
  .issue-card .date .day {{ display: block; font-size: var(--t-micro); color: var(--ink-mute); text-transform: uppercase; letter-spacing: 0.08em; margin-top: 0.15rem; }}
  .issue-card .content {{ min-width: 0; }}
  .issue-card .headline {{ font-family: 'Fraunces', serif; font-weight: 500; font-size: var(--t-h3); line-height: 1.2; color: var(--ink); margin: 0 0 0.4rem; }}
  .issue-card .summary {{ font-size: var(--t-small); color: var(--ink-soft); line-height: 1.45; margin: 0; }}
  .issue-card .counts {{ display: flex; flex-direction: column; align-items: flex-end; gap: 0.25rem; font-size: var(--t-micro); font-family: 'Geist Mono', monospace; color: var(--ink-mute); white-space: nowrap; }}
  .count-tag {{ display: inline-flex; align-items: center; gap: 0.3rem; }}
  .count-tag .dot {{ width: 0.45rem; height: 0.45rem; border-radius: 999px; }}
  .dot-crit {{ background: var(--tier-crit); }} .dot-look {{ background: var(--tier-look); }} .dot-fyi {{ background: var(--tier-fyi); }}
  .issue-card.weekly .headline::before {{ content: "{weekly_prefix}"; color: var(--ink-mute); font-family: 'Geist', sans-serif; font-size: 0.85em; }}
  .empty-state {{ text-align: center; padding: 4rem 1rem; color: var(--ink-mute); font-family: 'Fraunces', serif; font-style: italic; font-size: var(--t-h3); }}
  .footer {{ margin-top: 4rem; padding-top: 2rem; border-top: 1px solid var(--hairline-bold); color: var(--ink-mute); font-size: var(--t-small); }}
  .footer p {{ margin: 0.5rem 0; }}
  .footer .system {{ font-family: 'Geist Mono', monospace; font-size: var(--t-micro); }}
  @media (max-width: 520px) {{ .issue-card {{ grid-template-columns: 3.5rem 1fr; }} .issue-card .counts {{ grid-column: 2; align-items: flex-start; padding-top: 0.25rem; }} }}
</style>
</head>
<body>
<main class="page">
  <header class="masthead">
    <a href="./" class="logo">AI RADAR</a>
    <nav class="nav"><a href="./">{today_label}</a><a href="./archive.html" class="current">{archive_label}</a></nav>
  </header>
  <section class="cover">
    <span class="kicker smallcaps">AI Radar · {archive_label}</span>
    <h1 class="display">{cfg['archive_title']}</h1>
    <p class="lead">{cfg['archive_lead']}</p>
  </section>
  <div id="issues" class="issues-list"><div class="empty-state">Loading...</div></div>
  <footer class="footer">
    <p class="display-italic" style="font-size: var(--t-h3); color: var(--ink-soft); margin-bottom: 1rem;">{footer}</p>
    <p>{find_hint} <kbd class="mono">Ctrl+F</kbd> / <kbd class="mono">Cmd+F</kbd>.</p>
    <p class="system">ai-radar · archive · {lang}</p>
  </footer>
</main>
<script>
(async function () {{
  const list = document.getElementById('issues');
  function weekKey(dateStr, week) {{ return `Week ${{week}} · ${{dateStr.slice(0, 4)}}`; }}
  function counts(c) {{
    const out = [];
    if (c.crit) out.push(`<span class="count-tag"><span class="dot dot-crit"></span>${{c.crit}} 🚨</span>`);
    if (c.look) out.push(`<span class="count-tag"><span class="dot dot-look"></span>${{c.look}} 👀</span>`);
    if (c.fyi) out.push(`<span class="count-tag"><span class="dot dot-fyi"></span>${{c.fyi}} ℹ️</span>`);
    return out.join('');
  }}
  function escapeHtml(s) {{ return String(s ?? '').replace(/[&<>"']/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c])); }}
  try {{
    const res = await fetch('./archive.json', {{ cache: 'no-store' }});
    if (!res.ok) throw new Error('archive.json fetch failed: ' + res.status);
    const data = await res.json();
    const issues = (data.issues || []).slice().sort((a, b) => b.date.localeCompare(a.date));
    if (issues.length === 0) {{ list.innerHTML = '<div class="empty-state">{empty_text}</div>'; return; }}
    const groups = new Map();
    for (const iss of issues) {{ const key = weekKey(iss.date, iss.week); if (!groups.has(key)) groups.set(key, []); groups.get(key).push(iss); }}
    let html = '';
    for (const [weekLabel, items] of groups) {{
      html += `<div class="week-group"><div class="week-label">${{escapeHtml(weekLabel)}}</div>`;
      for (const iss of items) {{
        const kindClass = iss.kind === 'weekly' ? 'weekly' : 'daily';
        html += `<a class="issue-card ${{kindClass}}" href="${{escapeHtml(iss.url)}}"><div class="date">${{escapeHtml(iss.date.slice(5))}}<span class="day">${{escapeHtml(iss.weekday || '')}}</span></div><div class="content"><h3 class="headline">${{escapeHtml(iss.headline || '(untitled)')}}</h3><p class="summary">${{escapeHtml(iss.summary || '')}}</p></div><div class="counts">${{counts(iss.counts || {{}})}}</div></a>`;
      }}
      html += `</div>`;
    }}
    list.innerHTML = html;
  }} catch (err) {{
    list.innerHTML = `<div class="empty-state">{failed_text}: ${{escapeHtml(err.message)}}</div>`;
    console.error(err);
  }}
}})();
</script>
</body>
</html>
"""
    (site_dir / "archive.html").write_text(html)
    log(f"  wrote {site_dir.relative_to(RADAR)}/archive.html")


def git_push(commit_msg: str) -> None:
    log("  git add + commit + push...")
    subprocess.run(["git", "-C", str(RADAR), "add", "docs/", "output/"], check=True)
    r = subprocess.run(
        ["git", "-C", str(RADAR), "commit", "-m", commit_msg],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        if "nothing to commit" in r.stdout + r.stderr:
            log("  (nothing to commit — files unchanged)")
            return
        log(f"  ⚠️ commit failed: {r.stderr}")
        raise RuntimeError("git commit failed")
    subprocess.run(["git", "-C", str(RADAR), "push", "origin", "main"], check=True)
    log("  ✅ pushed")


def wait_for_pages_build(today: str, max_wait: int = 360) -> bool:
    """Wait until GitHub Pages actually serves today's content.

    We trust ACTUAL HTTP responses over the gh api build-status — Pages can
    report 'built' before CDN cache refreshes, AND Pages can get stuck
    'building' (e.g. Jekyll hang) while the deployment is actually fine.

    Strategy:
      1. Poll the live URL every 10s.
      2. Verify the response body contains today's date marker.
      3. Return True as soon as today's content is live.
      4. Bail after max_wait — caller still posts Discord but with a warning.
    """
    import urllib.request as _ur
    import urllib.error as _ue

    log(f"  ⏳ waiting for Pages to actually serve {today} content (max {max_wait}s)...")
    deadline = time.time() + max_wait
    expected_marker = today.replace("-", " · ")  # matches "2026 · 05 · 26" in HTML

    while time.time() < deadline:
        try:
            req = _ur.Request(
                GITHUB_PAGES_URL,
                headers={
                    "User-Agent": "AI-Radar-Verifier/1.0",
                    "Cache-Control": "no-cache",
                },
            )
            with _ur.urlopen(req, timeout=15) as r:
                body = r.read(50000).decode("utf-8", errors="replace")
            if expected_marker in body:
                elapsed = int(time.time() - (deadline - max_wait))
                log(f"  ✅ Pages serving {today} (after {elapsed}s)")
                return True
            else:
                # Show what date IS being served, for debugging
                import re as _re
                m = _re.search(r'date-line">([^<]+)', body)
                serving = m.group(1).strip() if m else "(no date found)"
                log(f"    still serving: {serving[:40]}, retrying...")
        except (_ue.URLError, _ue.HTTPError) as e:
            log(f"    fetch error: {e}, retrying...")
        except Exception as e:
            log(f"    unexpected: {e}, retrying...")
        time.sleep(10)
    log(f"  ⚠️ {max_wait}s elapsed and Pages still not serving {today} — posting Discord anyway with a warning note")
    return False


def discord_post(secrets: dict, content: str, file_path: Path | None = None) -> None:
    token = secrets["DISCORD_BOT_TOKEN"]
    url = f"https://discord.com/api/v10/channels/{DISCORD_CHANNEL_ID}/messages"

    # Discord requires User-Agent in format: DiscordBot (URL, VERSION)
    # See https://discord.com/developers/docs/reference#user-agent
    common_headers = {
        "Authorization": f"Bot {token}",
        "User-Agent": "DiscordBot (https://github.com/ethan-m25/ai-radar, 1.0)",
    }

    if file_path and file_path.exists():
        # multipart/form-data with file
        boundary = "----AIRADAR" + uuid.uuid4().hex
        body_parts = []
        # payload_json
        body_parts.append(f"--{boundary}\r\n".encode())
        body_parts.append(
            b'Content-Disposition: form-data; name="payload_json"\r\n'
            b"Content-Type: application/json\r\n\r\n"
        )
        body_parts.append(json.dumps({
            "content": content,
            "attachments": [{"id": 0, "filename": file_path.name}],
        }).encode())
        body_parts.append(f"\r\n--{boundary}\r\n".encode())
        # file
        body_parts.append(
            f'Content-Disposition: form-data; name="files[0]"; filename="{file_path.name}"\r\n'.encode()
        )
        body_parts.append(b"Content-Type: text/html\r\n\r\n")
        body_parts.append(file_path.read_bytes())
        body_parts.append(f"\r\n--{boundary}--\r\n".encode())
        body = b"".join(body_parts)
        headers = {
            **common_headers,
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        }
    else:
        body = json.dumps({"content": content}).encode()
        headers = {
            **common_headers,
            "Content-Type": "application/json",
        }

    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            log(f"  ✅ Discord posted (status {r.status})")
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        log(f"  ❌ Discord HTTP {e.code}: {err[:500]}")
        raise


# ────────────────────────── prompt construction ──────────────────────────

def build_system_prompt(lang: str) -> str:
    base = PROMPT_FILE.read_text() if PROMPT_FILE.exists() else ""
    language_rule = {
        "zh": """Target language: Simplified Chinese only.

Override any earlier bilingual-format instruction. Do NOT write separate EN blocks. Translate any labels that should be user-facing into Simplified Chinese, while preserving product names, URLs, code terms, CSS class names, and JavaScript.""",
        "en": """Target language: English only.

Override any earlier bilingual-format instruction. Do NOT write Chinese blocks and do NOT include a language toggle. Translate all user-facing Chinese template text into natural English, while preserving product names, URLs, code terms, CSS class names, and JavaScript.""",
    }[lang]

    addendum = f"""

---

## Critical output rules (overrides above)

You are running via OpenRouter, NOT Claude Code CLI. You do NOT have WebFetch, Write, Bash, or MCP tools.
You are a pure text-in / text-out model.

{language_rule}

**Your sole output**: a single complete self-contained HTML file (<!doctype ...> through </html>).
No preamble. No explanation. No markdown fences. Just the HTML.

You will be given:
1. The structural HTML template (from the most recent daily digest) — match its CSS, classes, fonts, color tokens exactly.
2. Fetched source content as text dumps — extract the real news from them.

Generate the digest for the date specified by the user. Apply the OR-logic signal rules, hard exclude filters, and 1-3 item cap.

Do NOT invent numbers, KOLs, or stories not actually present in the fetched sources. If you can't verify a story, drop it.

If fetched sources are sparse or all repeat yesterday's stories, produce 1 honest item or the "no real signals today" page.
"""
    return base + addendum


def build_user_prompt(today: str, weekday: str, week: int, issue_num: int,
                      sources: dict, template_html: str, history_text: str,
                      lang: str, reference_html: str | None = None) -> str:
    target = "Simplified Chinese" if lang == "zh" else "English"
    source_sections = []
    for name, cfg in SOURCES.items():
        source_sections.append(f"""### {cfg['label']}

{sources.get(name, "[no data]")[:cfg['max_chars']]}""")

    reference_section = ""
    if reference_html:
        reference_section = f"""
---

## REFERENCE ISSUE TO TRANSLATE/LOCALIZE

Use this already-generated Chinese issue as the canonical source of truth for item selection, tiering, ordering, evidence, links, and counts. For the English site, translate/localize the same issue into English. Do NOT add, drop, or re-rank items.

{reference_html[:70000]}
"""

    return f"""Today is **{today}** ({weekday}, ISO week {week}). Generate AI Radar issue №{issue_num:03d}.

Target output language: **{target}**.

## STRUCTURAL TEMPLATE (use this CSS, classes, layout exactly — replace content only)

{template_html}

---

## PAST 7 DAYS (apply Carry-over rules from system prompt)

{history_text}

---

## FETCHED SOURCES (raw text dumps — extract real news from these)

{chr(10).join(source_sections)}

{reference_section}

---

## YOUR TASK

Produce the {target} HTML for issue №{issue_num:03d} ({today}).

- Apply max 3 items rule (min 1)
- Exclude funding/drama/lawsuits/policy/pure-research/Chinese-already-covered
- **Apply Rule A (re-evaluate KILLED-list candidates)** — if any has grown in signal, promote it
- **Apply Rule B (suppress + sidebar)** — previously-featured items cannot occupy top-3 unless a trigger event occurred; otherwise put them in the `<aside class="still-tracking">` section (max 5 lines)
- Each 🚨/👀 in top-3 must have all required sections (Context / Why this matters / Action / Deep dive / Watch / Jargon / Who's talking / Links), in {target} only
- Both pagers must have `data-current-date="{today}"`
- All issue-counter spans use the new issue number ({issue_num:03d})
- Keep the JS at the bottom verbatim — it loads archive.json for prev/next

Output ONLY the complete HTML, nothing else.
"""


# ────────────────────────── main ──────────────────────────

def parse_html_summary(html: str) -> tuple[str, str, dict]:
    import re
    m = re.search(r'<h1 class="display headline">(.*?)</h1>', html, re.S)
    headline = (m.group(1).strip() if m else "(no headline)").replace("\n", " ")
    m = re.search(r'<p class="lead">(.*?)</p>', html, re.S)
    lead = (m.group(1).strip() if m else "")
    headline = re.sub(r"<[^>]+>", "", headline)[:120]
    lead = re.sub(r"<[^>]+>", "", lead)[:160]
    counts = {
        "crit": len(re.findall(r'<article[^>]*class="[^"]*item--crit', html)),
        "look": len(re.findall(r'<article[^>]*class="[^"]*item--look', html)),
        "fyi":  len(re.findall(r'<article[^>]*class="[^"]*item--fyi', html)),
    }
    return headline, lead, counts


def normalize_langs(value: str) -> list[str]:
    if value == "both":
        return ["zh", "en"]
    return [value]


def issue_number_for_date(today: str) -> int:
    if ARCHIVE_FILE.exists():
        arc = json.loads(ARCHIVE_FILE.read_text())
        daily_count = sum(1 for i in arc.get("issues", []) if i.get("kind") == "daily")
        issue_num = daily_count + 1
        existing = [i for i in arc.get("issues", []) if i.get("date") == today and i.get("kind") == "daily"]
        if existing:
            issue_num = existing[0].get("issue", issue_num)
        return issue_num
    return 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true",
                    help="Write to *-test.html and skip overwriting index.html")
    ap.add_argument("--no-discord", action="store_true", help="Skip Discord post")
    ap.add_argument("--no-git", action="store_true", help="Skip git push")
    ap.add_argument("--date", default=None, help="Override date (YYYY-MM-DD)")
    ap.add_argument("--lang", choices=["zh", "en", "both"], default="both",
                    help="Generate Chinese site, English site, or both")
    args = ap.parse_args()

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    for cfg in LANGS.values():
        cfg["site_dir"].mkdir(parents=True, exist_ok=True)
        cfg["raw_dir"].mkdir(parents=True, exist_ok=True)

    now = datetime.now()
    today = args.date or now.strftime("%Y-%m-%d")
    weekday = datetime.strptime(today, "%Y-%m-%d").strftime("%a")
    iso_year, iso_week, _ = datetime.strptime(today, "%Y-%m-%d").isocalendar()
    langs = normalize_langs(args.lang)

    log(f"=== AI Radar run starting · {today} ({weekday}) · Wk {iso_week} · test={args.test} · lang={args.lang} ===")

    secrets = load_secrets()
    log(f"  loaded secrets: OPENROUTER_API_KEY={'set' if secrets.get('OPENROUTER_API_KEY') else 'missing'}, DISCORD_BOT={secrets.get('DISCORD_BOT_SOURCE','?')}")

    issue_num = issue_number_for_date(today)
    log(f"  issue number: №{issue_num:03d}")

    log("Fetching sources...")
    sources = fetch_sources()

    log("Loading Chinese template/history...")
    zh_template_path = find_latest_html_template(LANGS["zh"]["site_dir"])
    if zh_template_path is None:
        log("❌ No existing daily HTML found — need at least one prior issue as template")
        sys.exit(2)
    log(f"  zh template: {zh_template_path.name} ({zh_template_path.stat().st_size} bytes)")
    zh_template_html = zh_template_path.read_text()

    log("Extracting history (past 7 days)...")
    history = extract_history(n_days=7, exclude_date=today, site_dir=LANGS["zh"]["site_dir"])
    history_text = format_history_for_prompt(history)

    results = {}
    usage_total = 0
    zh_reference_html = None

    for lang in langs:
        cfg = LANGS[lang]
        log(f"Generating {cfg['name']} issue...")

        if lang == "zh":
            template_html = zh_template_html
            reference_html = None
        else:
            en_template_path = find_latest_html_template(cfg["site_dir"])
            template_html = en_template_path.read_text() if en_template_path else zh_template_html
            zh_today_path = LANGS["zh"]["site_dir"] / f"{today}.html"
            reference_html = zh_reference_html
            if reference_html is None and zh_today_path.exists():
                reference_html = zh_today_path.read_text()

        system = build_system_prompt(lang)
        user = build_user_prompt(today, weekday, iso_week, issue_num, sources,
                                 template_html, history_text, lang,
                                 reference_html=reference_html)
        log(f"  prompt size ({lang}): system={len(system)}, user={len(user)} chars (~{(len(system)+len(user))//4} tokens)")
        raw, usage = call_openrouter(secrets, system, user)
        usage_total += usage.get("total_tokens", 0)

        html = extract_html(raw)
        if not html.lower().startswith("<!doctype"):
            log(f"⚠️ {lang} output doesn't start with <!doctype, first 200 chars:\n{html[:200]}")
        if "</html>" not in html.lower():
            log(f"⚠️ {lang} output missing </html> closing tag")

        out_name = f"{today}-deepseek-test.html" if args.test else f"{today}.html"
        out_html = cfg["site_dir"] / out_name
        out_html.write_text(html)
        log(f"  wrote {out_html.relative_to(RADAR)} ({len(html)} bytes)")

        raw_html = cfg["raw_dir"] / out_name
        raw_html.write_text(html)

        if not args.test:
            (cfg["site_dir"] / "index.html").write_text(html)
            log(f"  updated {cfg['site_dir'].relative_to(RADAR)}/index.html")

        headline, lead, counts = parse_html_summary(html)
        log(f"  parsed {lang}: headline='{headline[:60]}...', counts={counts}")

        if not args.test:
            if lang == "zh":
                update_archive_json(cfg["archive_file"], today, weekday, iso_week,
                                    headline, lead, counts, out_html.name)
            else:
                entry = {
                    "date": today,
                    "weekday": weekday,
                    "week": iso_week,
                    "issue": issue_num,
                    "kind": "daily",
                    "headline": headline,
                    "summary": lead,
                    "counts": counts,
                    "url": out_html.name,
                }
                sync_archive_json(LANGS["zh"]["archive_file"], cfg["archive_file"], entry)
            write_archive_page(lang)

        if lang == "zh":
            zh_reference_html = html

        results[lang] = {
            "html": html,
            "out_html": out_html,
            "headline": headline,
            "lead": lead,
            "counts": counts,
        }

    # Git push
    pages_verified = False
    if not args.no_git:
        suffix = " (TEST)" if args.test else ""
        headline_for_commit = results.get("zh", next(iter(results.values())))["headline"]
        lang_suffix = "" if args.lang == "zh" else f" [{args.lang}]"
        commit_msg = f"digest: {today} — {headline_for_commit[:60]}{suffix}{lang_suffix}\n\n[via OpenRouter / {MODEL}]"
        try:
            git_push(commit_msg)
            if not args.test:
                # Verify Pages actually serves today's content before claiming success
                pages_verified = wait_for_pages_build(today, max_wait=360)
        except Exception as e:
            log(f"  ⚠️ git push failed: {e} — continuing with Discord anyway")

    # Discord post
    if not args.no_discord and results:
        primary = results.get("zh", next(iter(results.values())))
        counts = primary["counts"]
        headline = primary["headline"]
        lead = primary["lead"]
        tier_line = []
        if counts["crit"]: tier_line.append(f"🚨 {counts['crit']} 必看")
        if counts["look"]: tier_line.append(f"👀 {counts['look']} 可看")
        if counts["fyi"]:  tier_line.append(f"ℹ️ {counts['fyi']} 知道")
        tier_str = " · ".join(tier_line) if tier_line else "0 真信号"

        zh_url = GITHUB_PAGES_URL + (primary["out_html"].name if args.test else "")
        en_part = ""
        if "en" in results:
            en_url = LANGS["en"]["base_url"] + (results["en"]["out_html"].name if args.test else "")
            en_part = f"\nEN: {en_url}"
        prefix = "🧪 **AI Radar TEST RUN**\n" if args.test else "🛰️ "
        suffix_note = "\n\n_(via OpenRouter + DeepSeek V4 Flash — 与 Claude 版本对比用)_" if args.test else ""

        # If Pages didn't catch up, warn user that the link may show stale content
        if not args.test and not pages_verified:
            suffix_note = "\n\n⚠️ _Pages 还在 build，链接可能仍显示昨天内容 1-2 分钟，刷新页面即可_"

        msg = f"""{prefix}**AI Radar · {today} · Wk {iso_week} · №{issue_num:03d}**

{tier_str}

**{headline}**
{lead}

ZH: {zh_url}{en_part}

📎 .html 附件供离线 / 对比用{suffix_note}"""

        # Discord 2000 char limit
        msg = msg[:1900]
        try:
            discord_post(secrets, msg, primary["out_html"])
        except Exception as e:
            log(f"❌ Discord post failed: {e}")

    log(f"=== Done · total tokens {usage_total} · cost estimate ≈ ${(usage_total * 1.5e-7):.4f} ===")


if __name__ == "__main__":
    main()
