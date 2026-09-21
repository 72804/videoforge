# First local real-generation canary (Phase 16B)

Authoritative product commit: `33d2101`. This document describes **Stage A** only.
Do not enable paid APIs, do not deploy, do not mutate production Neon.

## Existing Phase 16 path (unchanged)

```text
Product Project (CUSTOM_STORY, AUTO, 9:16, balanced)
  → engine_bridge.build_engine_spec
  → persist_engine_outline (script + scenes on MemoryRepository)
  → (Stage B later) freeze_plan + start_generation + RealGenerationWorker
  → engine adapters + local FFmpeg
  → artifacts/render/final/documentary_preview.mp4
```

Local canary wrapper: `docprod generation-canary`. It seeds an isolated in-memory
product user (`telegram_user_id=900001`) and project, then calls the same
`build_engine_spec` / `persist_engine_outline` used by the customer path.

It does **not** create a parallel generation engine. It does **not** use Neon,
Stars, Telegram webhook, Vercel, Cloud Run, or object storage.

## Blockers (documented, not redesigned)

| Item | Status |
| --- | --- |
| `ALLOW_PAID_GENERATION=false`, `ALLOW_PAID_APIS=false`, `REAL_GENERATION_DRY_RUN=true` | Required until explicit Stage B approval |
| `RealGenerationWorker` raises `LIVE_DISABLED` whenever dry-run is false | Stage B cannot run until that gate is lifted in a later approval |
| Dry-run writes placeholder bytes, not full subtitle/FFmpeg customer render | Acceptable for dry-run; live execute still blocked |
| Image / script / TTS catalog prices are unresolved or per-token | Frozen plan uses Phase 16 fallbacks; flag live verification |
| Migration `20260920_0003` | Not applied. Local canary uses `MemoryRepository` + `projects/videoforge_local_canary/` |

Do not treat R2, Cloud Run, or worker-wake as blockers for this canary.

## Canary content

- Slug: `videoforge_local_canary`
- Title: Suitcase in the basement
- Kind: `CUSTOM_STORY`
- Character: Nolan (generated identity; no uploaded reference)
- Duration mode: AUTO → 24s, 3 scenes (planner range 15–30s / 2–5 scenes)
- Aspect: 9:16
- Profile: Balanced, AUTO routing
- Max video shots: 1 (`CANARY_MAX_VIDEO_SHOTS`)

Typical frozen routing for this prompt:

1. Establishing still + local camera (`gpt-image-2.5-flare`)
2. Reaction → one Veo 3.1 Lite 8s shot
3. Static cinematic still + local camera

## First-canary providers (already in `FIRST_CANARY_PROVIDERS`)

| Step | Provider | Model |
| --- | --- | --- |
| Script | OpenAI | `gpt-5.6-luna` |
| Stills | OpenAI | `gpt-image-2.5-flare` |
| Video (at most one) | Google | `veo-3.1-lite-generate-preview` |
| TTS | OpenAI | `gpt-4o-mini-tts` |
| Music/SFX | local | `procedural-sfx` |
| Render | local | FFmpeg |

## Commands

Stage A (zero provider HTTP):

```bash
uv run docprod generation-canary --stage plan
```

Stage B (do not run until explicit approval):

```bash
uv run docprod generation-canary --stage execute
```

`--slug` must be `videoforge_local_canary`. Other slugs are refused.

## Local artifacts

Under `projects/videoforge_local_canary/` (gitignored):

- `product_store.json` — isolated MemoryRepository dump
- `artifacts/review/stage_a_plan.json`
- `artifacts/review/stage_a_report.md`
- `artifacts/render/final/documentary_preview.mp4` — created only in Stage B

## Stage B env (local ignored `.env` only — never Vercel)

```text
GENERATION_MODE=real
REAL_GENERATION_DRY_RUN=false
ALLOW_PAID_GENERATION=true
ALLOW_PAID_APIS=true
OPENAI_API_KEY=<local>
GEMINI_API_KEY=<local, if Veo remains in the frozen plan>
CANARY_MAX_PROVIDER_USD=2.0
```

Hard cap: **$2.00**. Prefer expected spend under **$1**.

Until `LIVE_DISABLED` is lifted, Stage B still refuses even with those flags.

## Isolation

- No Stars payment, no `StarTransaction`
- Sentinel Telegram id 900001 is not a customer account
- Production Mini App / webhook / Neon unchanged
