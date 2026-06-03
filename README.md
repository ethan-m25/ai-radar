# AI Radar

**clawii 的 AI 虚拟朋友** — 每天读一线英文 AI 一手源，用大白话告诉你"哪条该看 / 为什么这次升温 / 怎么用"。

## What this is

A daily AI tech digest generated through OpenClaw/OpenRouter, designed for one specific person (clawii) — a non-developer who vibe-codes and wants to catch big AI shifts within 7-10 days, not 4-6 weeks later.

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
                    │ OpenRouter + prompt   │
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
    │ YYYY-MM-DD.html  │          │ #cc-workspace   │
    └──────────────────┘          └─────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                     Tier 3 (future)                              │
└─────────────────────────────────────────────────────────────────┘

    output/*.html  →  static site  →  RSS / public web
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
│   ├── run_daily.sh           # daily wrapper (OpenRouter/OpenClaw)
│   ├── run_daily.py           # daily orchestrator
│   ├── run_weekly.sh          # weekly wrapper (OpenRouter/OpenClaw)
│   ├── run_weekly.py          # weekly orchestrator
│   └── test_digest.sh         # manual test run
├── output/
│   ├── YYYY-MM-DD.html        # Chinese daily archive copy
│   └── en/YYYY-MM-DD.html     # English daily archive copy
└── docs/
    ├── index.html             # Chinese daily site
    ├── en/index.html          # English daily site
    ├── archive.json           # Chinese archive
    └── en/archive.json        # English archive
```

## How it runs

**Daily at 07:07**: launchd fires `run_daily.sh` → fetches sources → calls OpenRouter using OpenClaw credentials → writes Chinese pages under `docs/` and English pages under `docs/en/` → commits/pushes → pushes Discord.

**Weekly at Sunday 08:00**: launchd fires `run_weekly.sh` → synthesizes the past 7 daily pages through OpenRouter → writes Chinese and English weekly permalinks → commits/pushes → pushes Discord.

**Manual test**: `bash ~/ai-radar/scripts/test_digest.sh` (uses today's sources, writes test HTML, no Git/Discord).

**URLs**:

- Chinese: `https://ethan-m25.github.io/ai-radar/`
- English: `https://ethan-m25.github.io/ai-radar/en/`

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
