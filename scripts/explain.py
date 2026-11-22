"""Explainer pass: make each picked item say WHAT the thing is, not just why it was picked.

The selection pass only sees headlines, tweets and HN titles, so it can justify a pick
("HN 1292 分") but often can't explain it ("来源里只有一条推文"). This pass reads the
primary sources behind each item (tweet text via fxtwitter, pages via r.jina.ai) and,
when the Claude backend is available, lets it search the web, then rewrites the
explanation fields: what / meaning / actions / deep_dive.
"""

from __future__ import annotations

import copy
import json
import re
import urllib.request

import llm

MAX_DOCS_PER_ITEM = 3
MAX_DOC_CHARS = 6000
FETCH_TIMEOUT_S = 30
# Claude with web search explains best; fall back to the normal chain with fetched text only.
EXPLAIN_CHAIN = [("claude", "sonnet")]

TWEET_RE = re.compile(r"https?://(?:x|twitter)\.com/[^/]+/status/(\d+)")
URL_RE = re.compile(r"https?://[^\s)\]\"'<>]+")

PROMPT = """You are explaining AI news to clawii: a compensation manager at a large company, NOT a developer, \
who vibe-codes with Claude Code and codex. He reads this on his phone and knows nothing about the story beforehand.

The items below were already selected for today's digest. The selection is final. Your only job is to make each item \
EXPLAIN ITSELF, so that after reading it he actually understands the thing — not just that it is popular.

For each item write (Simplified Chinese; keep product/people names, URLs and code in their original form):

- "what" (它是什么): 2-4 plain sentences, ≤150 Chinese characters. What is this thing, concretely? What does it do, \
for whom, how does it work at a high level? Name the specifics (e.g. "Astra 是旗舰、Sol 是便宜日常款"). \
NO popularity, NO likes/HN points, NO "引发热议" here.
- "meaning" (意味着什么): 1-2 sentences, ≤80 Chinese characters. What changes because of it — for AI users in general \
and for clawii specifically. Be honest; "对你影响不大" is fine.
- "actions" (怎么用): 0-2 concrete steps: where to find it, what to click/type, who can access it (plan, region, price). \
Empty list if there is nothing to try.
- "deep_dive": 0-3 short paragraphs, each ≤80 Chinese characters: comparison with what he already uses, limits, caveats.

Rules:
- Use the PRIMARY SOURCES given for each item{web_rule}.
- Never invent facts, numbers, availability or prices. If after reading you still don't know what something is, \
say plainly what IS known and what is not (one sentence), don't pad.
- Explain jargon inline in parentheses the first time. Reading level: a smart 13-year-old.
- Do not change titles, tiers, links or signals.

Return ONLY a JSON object, no fences:
{{"items": [{{"index": 0, "what": "...", "meaning": "...", "actions": ["..."], "deep_dive": ["..."]}}]}}

ITEMS AND THEIR PRIMARY SOURCES:

{blocks}
"""

WEB_RULE = ", and use WebSearch/WebFetch to look up the official announcement or a reliable write-up whenever the sources are thin (e.g. just a tweet). Keep searching cheap: at most ~3 lookups per item"


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 AI-Radar/1.0",
                                               "Accept": "text/plain,application/json,*/*"})
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_S) as r:
        return r.read().decode("utf-8", errors="replace")


def _tweet_text(tweet_id: str) -> str:
    tweet = json.loads(_get(f"https://api.fxtwitter.com/i/status/{tweet_id}")).get("tweet", {})
    author = tweet.get("author", {}).get("screen_name", "?")
    parts = [f"@{author}: {tweet.get('text', '')}"]
    quote = tweet.get("quote") or {}
    if quote.get("text"):
        parts.append(f"(quoting @{quote.get('author', {}).get('screen_name', '?')}: {quote['text']})")
    return "\n".join(parts)


def _page_text(url: str) -> str:
    return _get(f"https://r.jina.ai/{url}")


def gather_sources(item: dict, log) -> list[str]:
    """Fetch readable text for an item's links; tweets also pull the pages they link to."""
    urls = [str(l.get("url", "")) for l in item.get("links", []) if l.get("url")]
    docs: list[str] = []
    seen: set[str] = set()
    queue = list(urls)
    while queue and len(docs) < MAX_DOCS_PER_ITEM:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        try:
            m = TWEET_RE.match(url)
            if m:
                text = _tweet_text(m.group(1))
                queue += [u for u in URL_RE.findall(text) if not TWEET_RE.match(u)][:1]
            else:
                text = _page_text(url)
        except Exception as e:  # a dead link must not sink the issue
            log(f"    ⚠️ source fetch failed {url}: {type(e).__name__}: {e}")
            continue
        docs.append(f"[{url}]\n{text.strip()[:MAX_DOC_CHARS]}")
    return docs


def _item_block(idx: int, item: dict, docs: list[str]) -> str:
    draft = {k: item.get(k) for k in ("tier", "title", "what", "pitch", "why", "signals") if item.get(k)}
    sources = "\n\n".join(docs) if docs else "(no fetchable primary source)"
    return f"### Item {idx}\nDRAFT: {json.dumps(draft, ensure_ascii=False)}\n\nPRIMARY SOURCES:\n{sources}"


def _parse(text: str) -> list[dict]:
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    candidate = m.group(1) if m else text[text.find("{"): text.rfind("}") + 1]
    items = json.loads(candidate).get("items")
    if not isinstance(items, list):
        raise ValueError("explainer reply missing 'items'")
    return items


def _merge(data: dict, explained: list[dict]) -> dict:
    out = copy.deepcopy(data)
    for e in explained:
        idx = e.get("index")
        if not isinstance(idx, int) or not 0 <= idx < len(out["items"]):
            continue
        item = out["items"][idx]
        for key in ("what", "meaning"):
            if str(e.get(key, "")).strip():
                item[key] = str(e[key]).strip()
        for key in ("actions", "deep_dive"):
            if isinstance(e.get(key), list):
                item[key] = [str(x).strip() for x in e[key] if str(x).strip()]
    return out


def explain(data: dict, *, secrets: dict, log) -> tuple[dict, list[str]]:
    """Return (data with explanation fields rewritten, warnings). Never raises: on failure keeps the draft."""
    items = data.get("items", [])
    if not items:
        return data, []
    log("Explainer pass: fetching primary sources...")
    blocks = [_item_block(i, item, gather_sources(item, log)) for i, item in enumerate(items)]
    body = "\n\n---\n\n".join(blocks)
    attempts = [
        (EXPLAIN_CHAIN, True, PROMPT.format(web_rule=WEB_RULE, blocks=body)),
        (None, False, PROMPT.format(web_rule="", blocks=body)),
    ]
    warnings: list[str] = []
    for chain, web, prompt in attempts:
        try:
            text, label, failures = llm.complete(prompt, secrets=secrets, log=log, chain=chain, web=web)
            merged = _merge(data, _parse(text))
            log(f"  explainer done via {label}{' (+web)' if web else ''}")
            return merged, []
        except Exception as e:
            log(f"  ⚠️ explainer attempt failed: {type(e).__name__}: {e}")
            warnings.append(f"explainer: {e}"[:200])
    return data, warnings
