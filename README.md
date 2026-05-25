# AI Radar

**clawii 的 AI 虚拟朋友** — 每天读一线英文 AI 一手源，用大白话告诉你"哪条该看 / 为什么这次升温 / 怎么用"。

## What this is

A daily AI tech digest curated by Claude, designed for one specific person (clawii) — a non-developer who vibe-codes and wants to catch big AI shifts within 7-10 days, not 4-6 weeks later.

**Not** another AI newsletter that summarizes press releases. **This** filters real signals from cross-source momentum (X discussion, GitHub velocity, HN saturation, KOL endorsements) and writes them up as if a tech-savvy friend was texting you.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     Tier 1 + Tier 2 (current)                   │
└─────────────────────────────────────────────────────────────────┘

    ┌─────────────┐  ┌──────────────┐  ┌────────────┐  ┌────────┐
    │ Smol AI/    │  │ OSSInsight   │  │ HackerNews │  │ Anthrop│
    │ AINews      │  │ AI trending  │  │ front page │  │ /OpenAI│
    └──────┬──────┘  └──────┬───────┘  └──────┬─────┘  └────┬───┘
           │                │                  │             │
           └────────────────┴──────────────────┴─────────────┘
                                 │
                                 ▼
                    ┌───────────────────────┐
                    │  X feeds (10 KOLs)    │
                    │  via nitter/RSS       │
                    └───────────┬───────────┘
                                ▼
                    ┌───────────────────────┐
                    │  Claude (digest.md)   │
                    │  - clawii lens        │
                    │  - OR-logic signal    │
                    │  - 🚨 / 👀 / ℹ️ tier  │
                    │  - EN + ZH bilingual  │
                    │  - Friend tone        │
                    └───────────┬───────────┘
                                ▼
                ┌─────────────┴─────────────┐
                ▼                           ▼
    ┌──────────────────┐          ┌─────────────────┐
    │ output/          │          │ Discord push    │
    │ YYYY-MM-DD.md    │          │ #cc-workspace   │
    └──────────────────┘          └─────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                     Tier 3 (future)                              │
└─────────────────────────────────────────────────────────────────┘

    output/*.md  →  static site  →  RSS / public web
```

## Files

```
~/ai-radar/
├── README.md                  # this file
├── prompts/
│   └── digest.md              # THE prompt — defines persona, format, signal rules
├── sources/
│   └── sources.md             # source list with tiers and exclude rules
├── scripts/
│   ├── run_digest.sh          # daily orchestrator (calls Claude with digest.md)
│   └── test_digest.sh         # manual test run
├── output/
│   └── YYYY-MM-DD.md          # daily digests (committed for history)
└── docs/
    └── calibration.md         # tuning log over time
```

## How it runs

**Daily at 07:00**: `/schedule` fires `run_digest.sh` → fetches sources → runs Claude with `prompts/digest.md` → writes `output/YYYY-MM-DD.md` → pushes to Discord.

**Manual test**: `bash ~/ai-radar/scripts/test_digest.sh` (uses today's sources, prints to stdout, no Discord push).

## Calibration

- **Target**: 0-3 real signals per day
- **SLA**: 7-10 day lead time vs Chinese AI content cycle  
- **Acceptable**: Some days have 0 signals (don't fabricate)
- **Failure mode**: If user reports "I already knew this" >50% of the time, tighten filters; if "wait, why didn't you tell me about X" → relax filters or add sources

Calibration log in `docs/calibration.md`.

## Why not just subscribe to Smol AI?

Smol AI does the heavy lifting (cross-source aggregation), but it's written for AI engineers, runs long, and doesn't consistently explain "why this matters" in plain words. This system uses Smol AI as input and adds:

1. **Translation layer** — turns engineer-speak into 12-15 yo reading level
2. **Judgment layer** — applies a 🚨/👀/ℹ️ tier with explicit reasoning
3. **Filter layer** — removes funding/drama/policy noise that Smol AI includes
4. **Bilingual** — EN + ZH side by side
5. **Friend tone** — talks like a friend, not a publication
