#!/usr/bin/env python3
"""AI Radar weekly wrap orchestrator (OpenRouter/OpenClaw).

Generates standalone Chinese and English weekly pages without Claude Code CLI.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

from run_daily import (
    GITHUB_PAGES_URL,
    LANGS,
    LOG_DIR,
    MODEL,
    OUTPUT_DIR,
    OUTPUT_RAW_DIR,
    PROMPT_FILE,
    RADAR,
    build_system_prompt,
    call_openrouter,
    discord_post,
    extract_html,
    git_push,
    load_secrets,
    log,
    normalize_langs,
    parse_html_summary,
    sync_archive_json,
    write_archive_page,
)

WEEKLY_PROMPT_FILE = RADAR / "prompts" / "weekly_digest.md"


def collect_daily_inputs(today: str, lang: str) -> list[tuple[str, Path, str]]:
    site_dir = LANGS[lang]["site_dir"]
    today_dt = datetime.strptime(today, "%Y-%m-%d")
    dailies: list[tuple[str, Path, str]] = []
    for i in range(0, 7):
        d = today_dt - timedelta(days=i)
        date_str = d.strftime("%Y-%m-%d")
        path = site_dir / f"{date_str}.html"
        if path.exists():
            text = path.read_text()
            dailies.append((date_str, path, text[:55000]))
    return list(reversed(dailies))


def find_weekly_template(lang: str) -> str:
    site_dir = LANGS[lang]["site_dir"]
    candidates = sorted(site_dir.glob("weekly_*.html"), reverse=True)
    if candidates:
        return candidates[0].read_text()
    daily_candidates = sorted([p for p in site_dir.glob("2026-*.html") if "-test" not in p.stem], reverse=True)
    if daily_candidates:
        return daily_candidates[0].read_text()
    return (OUTPUT_DIR / "index.html").read_text()


def build_weekly_system_prompt(lang: str) -> str:
    base = WEEKLY_PROMPT_FILE.read_text() if WEEKLY_PROMPT_FILE.exists() else ""
    language_rule = {
        "zh": "Target language: Simplified Chinese only. Override the older bilingual instruction. Do not write separate EN blocks.",
        "en": "Target language: English only. Override the older bilingual instruction. Do not write Chinese blocks or a language toggle.",
    }[lang]
    return base + f"""

---

## Critical runtime rules (overrides above)

You are running via OpenRouter, not Claude Code. You have no tools.
{language_rule}

Your sole output is one complete self-contained HTML file, from <!doctype ...> through </html>.
Use the supplied template for CSS/classes/layout. Replace content only.
Do not invent new stories. Only synthesize the supplied daily issues.
"""


def build_weekly_user_prompt(today: str, weekday: str, iso_week: int, lang: str,
                             template_html: str,
                             daily_inputs: list[tuple[str, Path, str]],
                             reference_html: str | None = None) -> str:
    target = "Simplified Chinese" if lang == "zh" else "English"
    dailies = []
    for date_str, path, html in daily_inputs:
        dailies.append(f"""## Daily issue: {date_str}

Source file: {path}

{html}
""")

    reference_section = ""
    if reference_html:
        reference_section = f"""
---

## REFERENCE WEEKLY WRAP TO TRANSLATE/LOCALIZE

Use this Chinese weekly wrap as the canonical source of truth for the English page.
Keep the same sections, story choices, ordering, evidence, links, and tier counts.
Translate/localize only the user-facing text.

{reference_html[:70000]}
"""

    return f"""Today is {today} ({weekday}), ISO week {iso_week}. Generate the AI Radar weekly wrap.

Target output language: {target}.

## STRUCTURAL TEMPLATE

{template_html[:65000]}

---

## DAILY ISSUES FROM THE PAST 7 DAYS

{chr(10).join(dailies)}

{reference_section}

---

## TASK

Generate the {target} weekly HTML for Week {iso_week}.

Rules:
- Keep it strategic, not a recap.
- Pick the one thing that mattered most.
- Include trends building, overhyped/demoted calls, next-week watch list, and calibration metrics.
- Do not overwrite the daily homepage in the content; this file is a weekly permalink.
- Use links relative to this site. The current page filename is weekly_{today}.html.
- The archive link should be ./archive.html.
- Output only complete HTML.
"""


def weekly_counts(daily_inputs: list[tuple[str, Path, str]]) -> dict:
    counts = {"crit": 0, "look": 0, "fyi": 0}
    for _, _, html in daily_inputs:
        _, _, c = parse_html_summary(html)
        for k in counts:
            counts[k] += c.get(k, 0)
    return counts


def write_weekly_entry(lang: str, today: str, weekday: str, iso_week: int,
                       headline: str, lead: str, counts: dict,
                       out_name: str) -> None:
    entry = {
        "date": today,
        "weekday": weekday,
        "week": iso_week,
        "kind": "weekly",
        "headline": headline,
        "summary": lead[:160],
        "counts": counts,
        "url": out_name,
    }
    cfg = LANGS[lang]
    source_archive = LANGS["zh"]["archive_file"]
    sync_archive_json(source_archive, cfg["archive_file"], entry)
    write_archive_page(lang)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true", help="Write *-test weekly files")
    ap.add_argument("--no-discord", action="store_true")
    ap.add_argument("--no-git", action="store_true")
    ap.add_argument("--date", default=None)
    ap.add_argument("--lang", choices=["zh", "en", "both"], default="both")
    args = ap.parse_args()

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    for cfg in LANGS.values():
        cfg["site_dir"].mkdir(parents=True, exist_ok=True)
        cfg["raw_dir"].mkdir(parents=True, exist_ok=True)

    today = args.date or datetime.now().strftime("%Y-%m-%d")
    dt = datetime.strptime(today, "%Y-%m-%d")
    weekday = dt.strftime("%a")
    _, iso_week, _ = dt.isocalendar()
    langs = normalize_langs(args.lang)

    log(f"=== AI Radar weekly run · {today} · Wk {iso_week} · test={args.test} · lang={args.lang} ===")
    secrets = load_secrets()
    log(f"  loaded secrets: OPENROUTER_API_KEY={'set' if secrets.get('OPENROUTER_API_KEY') else 'missing'}, DISCORD_BOT={secrets.get('DISCORD_BOT_SOURCE','?')}")

    zh_inputs = collect_daily_inputs(today, "zh")
    if not zh_inputs:
        log("No Chinese daily issues in the past 7 days; skipping weekly.")
        sys.exit(0)
    log(f"  collected {len(zh_inputs)} Chinese daily issues")

    results = {}
    usage_total = 0
    zh_reference_html = None

    for lang in langs:
        cfg = LANGS[lang]
        daily_inputs = collect_daily_inputs(today, lang)
        if lang == "en" and not daily_inputs:
            daily_inputs = zh_inputs
        if not daily_inputs:
            log(f"  no daily inputs for {lang}; skipping")
            continue

        template_html = find_weekly_template(lang)
        reference_html = zh_reference_html if lang == "en" else None
        log(f"Generating weekly {cfg['name']} page from {len(daily_inputs)} dailies...")

        system = build_weekly_system_prompt(lang)
        user = build_weekly_user_prompt(today, weekday, iso_week, lang,
                                        template_html, daily_inputs,
                                        reference_html=reference_html)
        log(f"  prompt size ({lang}): system={len(system)}, user={len(user)} chars (~{(len(system)+len(user))//4} tokens)")
        raw, usage = call_openrouter(secrets, system, user)
        usage_total += usage.get("total_tokens", 0)
        html = extract_html(raw)

        out_name = f"weekly_{today}-test.html" if args.test else f"weekly_{today}.html"
        out_html = cfg["site_dir"] / out_name
        raw_html = cfg["raw_dir"] / out_name
        out_html.write_text(html)
        raw_html.write_text(html)
        log(f"  wrote {out_html.relative_to(RADAR)} ({len(html)} bytes)")

        headline, lead, parsed_counts = parse_html_summary(html)
        counts = weekly_counts(daily_inputs) or parsed_counts
        log(f"  parsed {lang}: headline='{headline[:60]}...', counts={counts}")

        if not args.test:
            write_weekly_entry(lang, today, weekday, iso_week, headline, lead, counts, out_name)

        if lang == "zh":
            zh_reference_html = html

        results[lang] = {
            "out_html": out_html,
            "headline": headline,
            "lead": lead,
            "counts": counts,
        }

    if not results:
        log("No weekly pages generated.")
        sys.exit(1)

    if not args.no_git:
        headline = results.get("zh", next(iter(results.values())))["headline"]
        suffix = " (TEST)" if args.test else ""
        commit_msg = f"weekly: Week {iso_week} wrap{suffix}\n\n{headline[:100]}\n\n[via OpenRouter / {MODEL}]"
        try:
            git_push(commit_msg)
        except Exception as e:
            log(f"  ⚠️ git push failed: {e} — continuing with Discord anyway")

    if not args.no_discord:
        primary = results.get("zh", next(iter(results.values())))
        zh_url = GITHUB_PAGES_URL + primary["out_html"].name if "zh" in results else ""
        en_url = LANGS["en"]["base_url"] + results["en"]["out_html"].name if "en" in results else ""
        msg = f"""📅 **AI Radar — Week {iso_week} Wrap**

**{primary['headline']}**
{primary['lead']}

ZH: {zh_url}
EN: {en_url}

📎 weekly .html attached"""
        try:
            discord_post(secrets, msg[:1900], primary["out_html"])
        except Exception as e:
            log(f"❌ Discord post failed: {e}")

    log(f"=== Weekly done · total tokens {usage_total} · cost estimate ≈ ${(usage_total * 1.5e-7):.4f} ===")


if __name__ == "__main__":
    main()
