#!/usr/bin/env python3
"""Re-run the explainer pass on already-published daily issues and re-render them.

Keeps each issue's picks, tiers, links and headline; only rewrites the explanation
fields (what / meaning / actions / deep_dive). Used for the 2026-11-22 catch-up.

    python3 scripts/reexplain.py 2026-11-16 2026-11-22
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta

import explain
import render
from run_daily import (LANGS, build_translate_prompt, generate_json, issue_number_for_date,
                       load_secrets, log)


def dates_between(start: str, end: str) -> list[str]:
    d, last = datetime.strptime(start, "%Y-%m-%d"), datetime.strptime(end, "%Y-%m-%d")
    out = []
    while d <= last:
        out.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=1)
    return out


def redo(date: str, secrets: dict) -> None:
    zh_json = LANGS["zh"]["raw_dir"] / f"{date}.json"
    if not zh_json.exists():
        log(f"  skip {date}: no JSON")
        return
    data = json.loads(zh_json.read_text())
    if not data.get("items"):
        log(f"  skip {date}: no items")
        return
    data, warnings = explain.explain(data, secrets=secrets, log=log)
    if warnings:
        log(f"  ⚠️ {date}: explainer kept the old text ({warnings})")
        return
    for item in data["items"]:  # old fields are superseded once `what` exists
        if item.get("what"):
            item.pop("pitch", None)
            item.pop("why", None)
    dt = datetime.strptime(date, "%Y-%m-%d")
    week, issue = dt.isocalendar()[1], issue_number_for_date(date)
    datasets = {"zh": data}
    try:
        datasets["en"], _, _ = generate_json(build_translate_prompt(data), secrets)
    except Exception as e:
        log(f"  ⚠️ {date}: EN translation failed, keeping old EN page: {e}")
    for lang, d in datasets.items():
        cfg = LANGS[lang]
        page = render.render_daily(d, lang=lang, date=date, week=week, issue=issue)
        for folder in (cfg["site_dir"], cfg["raw_dir"]):
            (folder / f"{date}.html").write_text(page)
        if date == datetime.now().strftime("%Y-%m-%d"):
            (cfg["site_dir"] / "index.html").write_text(page)
        (cfg["raw_dir"] / f"{date}.json").write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n")
    log(f"  ✅ {date} re-explained ({len(data['items'])} items)")


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    secrets = load_secrets()
    for date in dates_between(sys.argv[1], sys.argv[2]):
        log(f"=== re-explain {date} ===")
        redo(date, secrets)


if __name__ == "__main__":
    main()
