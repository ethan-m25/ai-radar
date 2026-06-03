# AI Radar — Source List

## Tier A: Primary signal sources (always fetched)

| Source | URL | Type | Notes |
|---|---|---|---|
| Smol AI / AINews | https://news.smol.ai/issues/ | Aggregated newsletter | Broad early scan across X, Discord, Reddit, GitHub. Still the best first-pass source. |
| Hacker News | https://news.ycombinator.com | Aggregator | Look for AI items in the top 1-15, high-comment threads, and repeated appearances. |
| OSSInsight Trending AI | https://ossinsight.io/trending/ai | GitHub momentum dashboard | Use 28d growth to detect open-source velocity. |
| GitHub Trending | https://github.com/trending?since=daily | Raw repo breakout scan | Cross-check OSSInsight and catch non-AI-tagged repos. |

## Tier B: Official ship sources (always fetched, but filtered hard)

| Source | URL | Type | Notes |
|---|---|---|---|
| OpenAI News RSS | https://openai.com/news/rss | Official RSS | Preferred over the HTML page because the HTML is often Cloudflare-challenged. |
| OpenAI Developers RSS | https://developers.openai.com/rss.xml | Official developer feed | Catches Codex/API/cookbook/tool releases that may not hit the main news page. |
| Anthropic News | https://www.anthropic.com/news | Official | Claude/model/product ships; filter out policy, offices, hiring, funding. |
| Google DeepMind Blog | https://deepmind.google/blog/ | Official | Model/capability releases; filter out pure research with no artifact. |
| Mistral News | https://mistral.ai/news/ | Official | Model and platform releases, especially open/European AI signals. |
| Hugging Face Blog | https://huggingface.co/blog | Official/community platform | Open model/tool releases and ecosystem posts. |
| Hugging Face Trending Models | https://huggingface.co/models?sort=trending | Model momentum | Catch model releases that spike before blog/news coverage. |

## Tier C: Practitioner / KOL signal

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

Current non-X fallback:

| Source | URL | Use case |
|---|---|---|
| Simon Willison AI tag | https://simonwillison.net/tags/ai/ | Hands-on practitioner signal; useful for "I tried it" validation. |
| Latent Space podcast/newsletter | https://www.latent.space | Optional weekly deep judgment; not currently fetched daily to avoid recap drift. |

## Judgment rule after expansion

More sources must not mean more items.

- Top-3 still requires the original OR-logic signal threshold.
- Official announcements alone are not enough unless they ship something usable or trigger HN/KOL/GitHub momentum.
- Hugging Face/GitHub spikes are leads, not proof; promote only with enough usage evidence or a very clear artifact.
- Policy, safety, offices, hiring, funding, lawsuits, and generic thought pieces remain hard excludes.
- If the broader source set only confirms a story already covered yesterday, put it in Still tracking or kill it.

## Hard exclude (do NOT fetch)

- ❌ TechCrunch, The Verge, Wired — too slow, too much funding/drama
- ❌ Twitter trending tab — too noisy
- ❌ Chinese-language sources (red note, 量子位, 机器之心) — they're 2-4 weeks behind by design and represent confirmation, not signal
- ❌ Any "AI tool of the day" lists — pure SEO content

## Calibration target

- 0-3 real signals per day
- 7-10 day lead time vs Chinese-language content cycle
- Zero tolerance for filler / recap
