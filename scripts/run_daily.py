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

# Sources to fetch
SOURCES = {
    "smol_ai": "https://news.smol.ai/issues/",
    "ossinsight": "https://ossinsight.io/trending/ai",
    "hackernews": "https://news.ycombinator.com",
    "anthropic": "https://www.anthropic.com/news",
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
    for name, url in SOURCES.items():
        log(f"  fetch {name}: {url}")
        try:
            raw = http_get(url)
            out[name] = strip_html(raw)
            log(f"    → {len(out[name])} chars")
        except Exception as e:
            out[name] = f"[fetch failed: {type(e).__name__}: {e}]"
            log(f"    ⚠️ {e}")
    return out


def find_latest_html_template() -> Path | None:
    """Use most recent docs/*.html (NOT index.html) as a structural reference."""
    candidates = sorted(
        [p for p in OUTPUT_DIR.glob("2026-*.html")],
        reverse=True,
    )
    return candidates[0] if candidates else None


def extract_history(n_days: int = 7, exclude_date: str | None = None) -> dict:
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
        path = OUTPUT_DIR / f"{date_str}.html"
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


def update_archive_json(today: str, weekday: str, week: int, headline: str,
                        summary: str, counts: dict, filename: str) -> None:
    if ARCHIVE_FILE.exists():
        data = json.loads(ARCHIVE_FILE.read_text())
    else:
        data = {"issues": []}

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
    ARCHIVE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    log(f"  updated archive.json: issue #{issue_num}")


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

def build_system_prompt() -> str:
    base = PROMPT_FILE.read_text() if PROMPT_FILE.exists() else ""

    addendum = """

---

## Critical output rules (overrides above)

You are running via OpenRouter, NOT Claude Code CLI. You do NOT have WebFetch, Write, Bash, or MCP tools.
You are a pure text-in / text-out model.

**Your sole output**: a single complete self-contained HTML file (<!doctype ...> through </html>).
No preamble. No explanation. No markdown fences. Just the HTML.

You will be given:
1. The structural HTML template (from the most recent daily digest) — match its CSS, classes, fonts, color tokens exactly.
2. Fetched source content (Smol AI, OSSInsight, HN, Anthropic news) as text dumps — extract the real news from them.

Generate the digest for the date specified by the user. Apply the OR-logic signal rules, hard exclude filters, and 1-3 item cap.

Do NOT invent numbers, KOLs, or stories not actually present in the fetched sources. If you can't verify a story, drop it.

If fetched sources are sparse or all repeat yesterday's stories, produce 1 honest item or the "no real signals today" page.
"""
    return base + addendum


def build_user_prompt(today: str, weekday: str, week: int, issue_num: int,
                      sources: dict, template_html: str, history_text: str) -> str:
    return f"""Today is **{today}** ({weekday}, ISO week {week}). Generate AI Radar issue №{issue_num:03d}.

## STRUCTURAL TEMPLATE (use this CSS, classes, layout exactly — replace content only)

{template_html}

---

## PAST 7 DAYS (apply Carry-over rules from system prompt)

{history_text}

---

## FETCHED SOURCES (raw text dumps — extract real news from these)

### news.smol.ai/issues/

{sources.get("smol_ai", "[no data]")[:18000]}

### ossinsight.io/trending/ai (top 28-day star growth)

{sources.get("ossinsight", "[no data]")[:8000]}

### news.ycombinator.com front page

{sources.get("hackernews", "[no data]")[:10000]}

### anthropic.com/news (last 5 announcements)

{sources.get("anthropic", "[no data]")[:6000]}

---

## YOUR TASK

Produce the HTML for issue №{issue_num:03d} ({today}).

- Apply max 3 items rule (min 1)
- Exclude funding/drama/lawsuits/policy/pure-research/Chinese-already-covered
- **Apply Rule A (re-evaluate KILLED-list candidates)** — if any has grown in signal, promote it
- **Apply Rule B (suppress + sidebar)** — previously-featured items cannot occupy top-3 unless a trigger event occurred; otherwise put them in the `<aside class="still-tracking">` section (max 5 lines)
- Each 🚨/👀 in top-3 must have all required sections (Context / Why this matters / Action / Deep dive / Watch / Jargon / Who's talking / Links + both EN and 中文 lang blocks)
- Both pagers must have `data-current-date="{today}"`
- All issue-counter spans use the new issue number ({issue_num:03d})
- Keep the JS at the bottom verbatim — it loads archive.json for prev/next

Output ONLY the complete HTML, nothing else.
"""


# ────────────────────────── main ──────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true",
                    help="Write to *-test.html and skip overwriting index.html")
    ap.add_argument("--no-discord", action="store_true", help="Skip Discord post")
    ap.add_argument("--no-git", action="store_true", help="Skip git push")
    ap.add_argument("--date", default=None, help="Override date (YYYY-MM-DD)")
    args = ap.parse_args()

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_RAW_DIR.mkdir(parents=True, exist_ok=True)

    now = datetime.now()
    today = args.date or now.strftime("%Y-%m-%d")
    weekday = datetime.strptime(today, "%Y-%m-%d").strftime("%a")
    iso_year, iso_week, _ = datetime.strptime(today, "%Y-%m-%d").isocalendar()

    log(f"=== AI Radar run starting · {today} ({weekday}) · Wk {iso_week} · test={args.test} ===")

    secrets = load_secrets()
    log(f"  loaded secrets: OPENROUTER_API_KEY={'set' if secrets.get('OPENROUTER_API_KEY') else 'missing'}, DISCORD_BOT={secrets.get('DISCORD_BOT_SOURCE','?')}")

    # Issue number based on existing archive
    if ARCHIVE_FILE.exists():
        arc = json.loads(ARCHIVE_FILE.read_text())
        daily_count = sum(1 for i in arc.get("issues", []) if i.get("kind") == "daily")
        issue_num = daily_count + 1
        if args.date:
            # if regenerating an existing date, reuse its number
            existing = [i for i in arc.get("issues", []) if i.get("date") == today and i.get("kind") == "daily"]
            if existing:
                issue_num = existing[0].get("issue", issue_num)
    else:
        issue_num = 1
    log(f"  issue number: №{issue_num:03d}")

    # Fetch sources
    log("Fetching sources...")
    sources = fetch_sources()

    # Get template
    log("Loading template (latest dated HTML)...")
    template_path = find_latest_html_template()
    if template_path is None:
        log("❌ No existing daily HTML found — need at least one prior issue as template")
        sys.exit(2)
    log(f"  template: {template_path.name} ({template_path.stat().st_size} bytes)")
    template_html = template_path.read_text()

    # Extract past-7-day history for carry-over rules
    log("Extracting history (past 7 days)...")
    history = extract_history(n_days=7, exclude_date=today)
    history_text = format_history_for_prompt(history)

    # Build prompts
    system = build_system_prompt()
    user = build_user_prompt(today, weekday, iso_week, issue_num, sources, template_html, history_text)
    log(f"  prompt size: system={len(system)}, user={len(user)} chars (~{(len(system)+len(user))//4} tokens)")

    # Call OpenRouter
    log("Calling OpenRouter...")
    raw, usage = call_openrouter(secrets, system, user)

    # Extract HTML
    html = extract_html(raw)
    if not html.lower().startswith("<!doctype"):
        log(f"⚠️ Output doesn't start with <!doctype, first 200 chars:\n{html[:200]}")
    if "</html>" not in html.lower():
        log("⚠️ Output missing </html> closing tag")

    # Write file
    if args.test:
        out_html = OUTPUT_DIR / f"{today}-deepseek-test.html"
    else:
        out_html = OUTPUT_DIR / f"{today}.html"
    out_html.write_text(html)
    log(f"  wrote {out_html} ({len(html)} bytes)")

    # Backup to output/
    raw_html = OUTPUT_RAW_DIR / out_html.name
    raw_html.write_text(html)

    # Update index.html (only on non-test run)
    if not args.test:
        (OUTPUT_DIR / "index.html").write_text(html)
        log("  updated index.html")

    # Extract summary fields from HTML for archive.json
    import re
    m = re.search(r'<h1 class="display headline">(.*?)</h1>', html, re.S)
    headline = (m.group(1).strip() if m else "(no headline)").replace("\n", " ")
    m = re.search(r'<p class="lead">(.*?)</p>', html, re.S)
    lead = (m.group(1).strip() if m else "")
    # Clean tags from headline/lead
    headline = re.sub(r"<[^>]+>", "", headline)[:120]
    lead = re.sub(r"<[^>]+>", "", lead)[:160]

    # Count tiers — match only <article> tags, not CSS class definitions
    counts = {
        "crit": len(re.findall(r'<article[^>]*class="[^"]*item--crit', html)),
        "look": len(re.findall(r'<article[^>]*class="[^"]*item--look', html)),
        "fyi":  len(re.findall(r'<article[^>]*class="[^"]*item--fyi', html)),
    }
    log(f"  parsed: headline='{headline[:60]}...', counts={counts}")

    # Update archive (only on non-test run)
    if not args.test:
        update_archive_json(today, weekday, iso_week, headline, lead, counts, out_html.name)

    # Git push
    pages_verified = False
    if not args.no_git:
        suffix = " (TEST)" if args.test else ""
        commit_msg = f"digest: {today} — {headline[:60]}{suffix}\n\n[via OpenRouter / {MODEL}]"
        try:
            git_push(commit_msg)
            if not args.test:
                # Verify Pages actually serves today's content before claiming success
                pages_verified = wait_for_pages_build(today, max_wait=360)
        except Exception as e:
            log(f"  ⚠️ git push failed: {e} — continuing with Discord anyway")

    # Discord post
    if not args.no_discord:
        tier_line = []
        if counts["crit"]: tier_line.append(f"🚨 {counts['crit']} 必看")
        if counts["look"]: tier_line.append(f"👀 {counts['look']} 可看")
        if counts["fyi"]:  tier_line.append(f"ℹ️ {counts['fyi']} 知道")
        tier_str = " · ".join(tier_line) if tier_line else "0 真信号"

        url = GITHUB_PAGES_URL + (f"{out_html.name}" if args.test else "")
        prefix = "🧪 **AI Radar TEST RUN**\n" if args.test else "🛰️ "
        suffix_note = "\n\n_(via OpenRouter + DeepSeek V4 Flash — 与 Claude 版本对比用)_" if args.test else ""

        # If Pages didn't catch up, warn user that the link may show stale content
        if not args.test and not pages_verified:
            suffix_note = "\n\n⚠️ _Pages 还在 build，链接可能仍显示昨天内容 1-2 分钟，刷新页面即可_"

        msg = f"""{prefix}**AI Radar · {today} · Wk {iso_week} · №{issue_num:03d}**

{tier_str}

**{headline}**
{lead}

👉 {url}

📎 .html 附件供离线 / 对比用{suffix_note}"""

        # Discord 2000 char limit
        msg = msg[:1900]
        try:
            discord_post(secrets, msg, out_html)
        except Exception as e:
            log(f"❌ Discord post failed: {e}")

    log(f"=== Done · cost ≈ ${(usage.get('total_tokens', 0) * 1.5e-7):.4f} ===")


if __name__ == "__main__":
    main()
