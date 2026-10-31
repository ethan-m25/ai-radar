"""Render a daily digest (structured JSON from the model) into the fixed HTML template.

The model never writes HTML any more: it returns JSON, and this module owns the
layout. That stops the template from drifting day over day (the old
"use yesterday's HTML as template" loop degraded issues from ~35KB to ~5KB) and
lets us hard-cap how much text reaches the page.
"""

from __future__ import annotations

import html
from pathlib import Path

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
CSS = (TEMPLATE_DIR / "daily.css").read_text()

TIERS = ("crit", "look", "fyi")

# Hard caps — the prompt asks for brevity, these guarantee it.
MAX_ITEMS = 3
MAX_WHY = 3
MAX_ACTIONS = 2
MAX_DEEP = 3
MAX_LINKS = 3
MAX_TRACKING = 3
MAX_SKIPPED = 5

LABELS = {
    "zh": {
        "tier": {"crit": "🚨 必看", "look": "👀 值得看", "fyi": "ℹ️ 知道就行"},
        "count": {"crit": "必看", "look": "值得看", "fyi": "知道就行"},
        "toc": "📋 今日目录",
        "why": "为什么重要",
        "actions": "🎯 你可以做",
        "deep": "🔬 深扒（点开看）",
        "signals": "信号",
        "links": "链接",
        "tracking": "📈 持续追踪",
        "skipped": "📊 今天没选进来的（点开看）",
        "skipped_head": ("候选", "为什么没进"),
        "empty": "🌤️ 今天没有真信号。扫过的内容都是 recap / 通稿 / 旧闻。Stay calm and keep building.",
        "prev": "← 前一天",
        "next": "后一天 →",
        "footer": "🛰️ AI Radar · 每天扫 Smol AI / HN / GitHub / X builders / 官方博客 · 只挑真信号",
        "archive": "归档",
    },
    "en": {
        "tier": {"crit": "🚨 Must see", "look": "👀 Worth a look", "fyi": "ℹ️ FYI"},
        "count": {"crit": "must see", "look": "worth a look", "fyi": "FYI"},
        "toc": "📋 Today",
        "why": "Why it matters",
        "actions": "🎯 What you can do",
        "deep": "🔬 Deep dive (tap to open)",
        "signals": "Signals",
        "links": "Links",
        "tracking": "📈 Still tracking",
        "skipped": "📊 Didn't make the cut (tap to open)",
        "skipped_head": ("Candidate", "Why not"),
        "empty": "🌤️ No real signals today. Everything scanned was recap, PR, or old news. Stay calm and keep building.",
        "prev": "← Previous",
        "next": "Next →",
        "footer": "🛰️ AI Radar · Scans Smol AI / HN / GitHub / X builders / official blogs daily · signal only",
        "archive": "Archive",
    },
}

PAGER_JS = """
(async function() {
    const currentDate = '%(date)s';
    let issues = [];
    try {
        const resp = await fetch('./archive.json');
        issues = (await resp.json()).issues || [];
    } catch (e) { return; }
    const idx = issues.findIndex(i => i.date === currentDate && i.kind === 'daily');
    if (idx === -1) return;
    const prev = issues.slice(idx + 1).find(i => i.kind === 'daily');
    const next = issues.slice(0, idx).reverse().find(i => i.kind === 'daily');
    document.querySelectorAll('.pager').forEach(p => {
        const prevLink = p.querySelector('.prev');
        const nextLink = p.querySelector('.next');
        if (prev) { prevLink.href = prev.url; prevLink.textContent = '← ' + prev.date; }
        else { prevLink.style.opacity = '0.3'; prevLink.style.pointerEvents = 'none'; }
        if (next) { nextLink.href = next.url; nextLink.textContent = next.date + ' →'; }
        else { nextLink.style.opacity = '0.3'; nextLink.style.pointerEvents = 'none'; }
    });
})();
"""

EXTRA_CSS = """
        details.skipped summary { cursor: pointer; }
        .signals { font-size: 0.85rem; opacity: 0.8; margin-top: 0.75rem; }
"""


def esc(value) -> str:
    return html.escape(str(value or "").strip())


def safe_url(url: str) -> str:
    url = str(url or "").strip()
    return html.escape(url, quote=True) if url.startswith(("https://", "http://")) else ""


def tier_of(item: dict) -> str:
    tier = str(item.get("tier", "fyi")).lower()
    return tier if tier in TIERS else "fyi"


def counts_of(data: dict) -> dict:
    items = data.get("items", [])[:MAX_ITEMS]
    return {t: sum(1 for i in items if tier_of(i) == t) for t in TIERS}


def _list(items: list, limit: int, tag: str = "ul") -> str:
    lis = "".join(f"<li>{esc(x)}</li>" for x in items[:limit] if str(x).strip())
    return f"<{tag}>{lis}</{tag}>" if lis else ""


def _links(links: list) -> str:
    out = []
    for link in links[:MAX_LINKS]:
        url = safe_url(link.get("url", ""))
        if url:
            out.append(f'<a href="{url}" target="_blank" rel="noopener">{esc(link.get("label") or url)}</a>')
    return " · ".join(out)


def render_item(idx: int, item: dict, L: dict) -> str:
    tier = tier_of(item)
    parts = [
        f'<article id="item{idx}" class="item item--{tier}">',
        f'    <div class="tier-label">{L["tier"][tier]}</div>',
        f'    <h2 class="display title">{esc(item.get("title"))}</h2>',
        f'    <div class="pitch">{esc(item.get("pitch"))}</div>',
    ]
    why = _list(item.get("why", []), MAX_WHY)
    if why:
        parts.append(f'    <div class="lang"><h3>{L["why"]}</h3>{why}</div>')
    actions = _list(item.get("actions", []), MAX_ACTIONS, "ol")
    if actions and tier != "fyi":
        parts.append(f'    <div class="action-block"><h3>{L["actions"]}</h3>{actions}</div>')
    deep = [d for d in item.get("deep_dive", [])[:MAX_DEEP] if str(d).strip()]
    if deep and tier != "fyi":
        paras = "".join(f"<p>{esc(d)}</p>" for d in deep)
        parts.append(f'    <details class="deep-dive"><summary>{L["deep"]}</summary><div class="dd-content">{paras}</div></details>')
    if item.get("signals"):
        parts.append(f'    <div class="signals"><strong>{L["signals"]}</strong> · {esc(item["signals"])}</div>')
    links = _links(item.get("links", []))
    if links:
        parts.append(f'    <div class="try-links"><strong>{L["links"]}</strong> · {links}</div>')
    parts.append("</article>")
    return "\n".join(parts)


def render_daily(data: dict, *, lang: str, date: str, week: int, issue: int) -> str:
    L = LABELS[lang]
    items = data.get("items", [])[:MAX_ITEMS]
    counts = counts_of(data)
    issue_label = f"№{issue:03d} · {date}"

    toc = "".join(
        f'<li><span class="tier-tag {tier_of(i)}">{L["tier"][tier_of(i)]}</span> {esc(i.get("title"))}</li>'
        for i in items
    )
    body_items = "\n\n".join(render_item(n, i, L) for n, i in enumerate(items, start=1))
    if not items:
        body_items = f'<article class="item item--fyi"><div class="pitch">{L["empty"]}</div></article>'

    tracking = "".join(
        f'<li><span class="days">Day {esc(t.get("day"))}</span>'
        f'<div><span class="item-name">{esc(t.get("name"))}</span> '
        f'<span class="update">— {esc(t.get("update"))}</span></div></li>'
        for t in data.get("still_tracking", [])[:MAX_TRACKING]
    )
    tracking_html = (
        f'<aside class="still-tracking"><span class="smallcaps">{L["tracking"]}</span><ul>{tracking}</ul></aside>'
        if tracking else ""
    )

    skipped_rows = "".join(
        f"<tr><td>{esc(s.get('name'))}</td><td>{esc(s.get('reason'))}</td></tr>"
        for s in data.get("skipped", [])[:MAX_SKIPPED]
    )
    head = L["skipped_head"]
    skipped_html = (
        f'<section class="killed"><details class="skipped"><summary class="smallcaps">{L["skipped"]}</summary>'
        f"<table><thead><tr><th>{head[0]}</th><th>{head[1]}</th></tr></thead><tbody>{skipped_rows}</tbody></table>"
        f"</details></section>"
        if skipped_rows else ""
    )

    pager = (
        f'<div class="pager" data-current-date="{date}">'
        f'<a href="#" class="prev">{L["prev"]}</a>'
        f'<span class="issue-num">{issue_label}</span>'
        f'<a href="#" class="next">{L["next"]}</a></div>'
    )
    html_lang = "zh-CN" if lang == "zh" else "en"

    return f"""<!doctype html>
<html lang="{html_lang}">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI Radar — {date} (Week {week})</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,400;0,9..144,500;0,9..144,600;0,9..144,700;1,9..144,400;1,9..144,500&family=Geist:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
{CSS}
{EXTRA_CSS}
</style>
</head>
<body>

<header class="masthead">
    <span class="logo">🛰️ AI Radar</span>
    <span class="meta date-line">{date.replace("-", " · ")} · Week {week} · №{issue:03d} · <a href="archive.html">{L["archive"]}</a></span>
</header>

<div class="cover">
    <h1 class="display headline">{esc(data.get("headline"))}</h1>
    <p class="lead">{esc(data.get("summary"))}</p>
    <div class="counts">
        <span>🚨 <span class="crit-count">{counts["crit"]}</span> {L["count"]["crit"]}</span>
        <span>👀 <span class="look-count">{counts["look"]}</span> {L["count"]["look"]}</span>
        <span>ℹ️ <span class="fyi-count">{counts["fyi"]}</span> {L["count"]["fyi"]}</span>
    </div>
</div>

{pager}

<nav class="toc"><span class="smallcaps">{L["toc"]}</span><ul>{toc}</ul></nav>

{body_items}

{tracking_html}

{skipped_html}

<footer class="footer"><p>{L["footer"]}</p></footer>

{pager}

<script>{PAGER_JS % {"date": date}}</script>
</body>
</html>
"""
