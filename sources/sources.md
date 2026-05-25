# AI Radar — Source List

## Tier A: Primary signal sources (always fetched)

| Source | URL | Type | Notes |
|---|---|---|---|
| Smol AI / AINews | https://news.smol.ai | Newsletter | Indexes 356 X + 21 Discord + Reddit + GitHub. Karpathy-endorsed. THE most important source. |
| OSSInsight Trending AI | https://ossinsight.io/trending/ai | Dashboard | Use 28d growth column to spot velocity. |
| Hacker News | https://news.ycombinator.com | Aggregator | Filter for AI-related items on front page. |
| Anthropic changelog | https://www.anthropic.com/news | Official | Model releases, feature ships. |
| OpenAI updates | https://openai.com/index/ | Official | Model releases, feature ships. |

## Tier B: KOL X feeds (best-effort, skip if rate-limited)

Use nitter mirrors or RSS bridges since X API is paywalled.

| Handle | Why |
|---|---|
| @karpathy | Andrej Karpathy — when he posts about a tool, the whole community follows |
| @swyx | swyx — runs Latent Space, very early signal on dev tooling |
| @simonw | Simon Willison — daily hands-on experiments, early adopter signal |
| @rileygoodside | Riley Goodside — prompt engineering, LLM weirdness |
| @skirano | Pietro Schirano — agent/UI experiments, often viral |
| @OfficialLoganK | Logan Kilpatrick — Google AI relations, ships news |
| @alexalbert__ | Alex Albert — Anthropic, ships news |
| @sama | Sam Altman — OpenAI, ships news (filter out drama) |
| @demishassabis | Demis Hassabis — DeepMind, occasional but important |
| @miramurati | Mira Murati — Thinking Machines |

## Tier C: Verification / fallback (used when Tier A misses something)

| Source | URL | Use case |
|---|---|---|
| GitHub Trending | https://github.com/trending?since=daily | Cross-check against OSSInsight |
| Latent Space podcast/newsletter | https://www.latent.space | Weekly deep judgment |
| Simon Willison weeknotes | https://simonwillison.net | Weekly synthesis |

## Hard exclude (do NOT fetch)

- ❌ TechCrunch, The Verge, Wired — too slow, too much funding/drama
- ❌ Twitter trending tab — too noisy
- ❌ Chinese-language sources (red note, 量子位, 机器之心) — they're 2-4 weeks behind by design and represent confirmation, not signal
- ❌ Any "AI tool of the day" lists — pure SEO content

## Calibration target

- 0-3 real signals per day
- 7-10 day lead time vs Chinese-language content cycle
- Zero tolerance for filler / recap
