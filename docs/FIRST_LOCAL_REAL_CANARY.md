# First local real-generation canary (Phase 16B)

Authoritative product commit for the architecture: `33d2101`.
This document covers Stage A (plan) and Stage B **preparation**.
Do not run `--stage execute` until explicit approval. Do not deploy.

## Path

```text
Product Project (CUSTOM_STORY, AUTO, 9:16, balanced)
  → engine_bridge.build_engine_spec (unit reservations)
  → persist_engine_outline
  → LocalCanaryWorker (canary slug only)
      OpenAIResponsesProvider (gpt-5.6-luna)
      OpenAIImageProvider (gpt-image-2.5-flare, 1024x1536 medium)
      GoogleVeoProvider (veo-3.1-lite-generate-preview, 8s 720p, journal recover)
      OpenAITTSProvider (gpt-4o-mini-tts)
      local procedural audio (no paid music)
      existing FFmpeg renderer + even-split subtitles
  → projects/videoforge_local_canary/artifacts/render/final/documentary_preview.mp4
```

Non-canary `RealGenerationWorker` live jobs still raise `LIVE_DISABLED`.

## Safety gates (all required before any provider HTTP)

1. `--stage execute` (or the explicit execute helper)
2. slug `videoforge_local_canary`
3. `GENERATION_MODE=real`
4. `REAL_GENERATION_DRY_RUN=false`
5. `ALLOW_PAID_GENERATION=true`
6. `ALLOW_PAID_APIS=true`
7. `$2.00` cap check before every paid ledger submit
8. existing paid fingerprint / Veo journal recovery (never a second submit)

Production Vercel stays `GENERATION_MODE=mock` and `ALLOW_PAID_*=false`.

## Operation order

1. Script (`gpt-5.6-luna`) — persist/clamp 2–5 scenes, 15–30s, ≤1 Veo shot, re-freeze remaining spend
2. Canonical character reference still for Nolan (`AUTO_GENERATED` CharacterReference)
3. Three scene stills with that reference (`images.edit` when the file exists)
4. At most one Veo Lite 8s 720p I2V from the chosen still (submit once, persist remote id, poll/resume)
5. TTS (`gpt-4o-mini-tts`)
6. Local procedural audio only
7. FFmpeg compose + deterministic even-split subtitles (no paid Whisper)

## Image settings

- size: `1024x1536` (9:16, no auto)
- quality: `medium` (not high/xhigh)
- format: `jpeg`
- no partial streaming

Reservation uses 2500 image-output tokens ($0.075) + 2000 text-in tokens ($0.01)
and, when a reference is attached, 2500 image-in tokens ($0.02).
Typical expected output is ~1584 medium tokens (~$0.0475) plus small text/ref usage.
Actual cost is reconciled from API usage when present.

## Current unit prices (this task)

| Unit | Rate |
| --- | --- |
| GPT-5.6 Luna input | $0.20 / 1M |
| GPT-5.6 Luna output | $1.20 / 1M |
| Flare text in | $5 / 1M |
| Flare image in | $8 / 1M |
| Flare image out | $30 / 1M |
| Veo 3.1 Lite 720p | $0.05 / s → 8s = **$0.40** |
| TTS text in | $0.60 / 1M |
| TTS audio out | $12 / 1M |

## Reservations vs expected

Conservative reserved (cap accounting):

- script: 20k in + 8k out → **$0.0136**
- character still (no ref): **$0.085**
- 3 scene stills with ref: 3 × **$0.105** = **$0.315**
- Veo 8s 720p: **$0.40**
- TTS: 2k text + 40k audio tokens (pre-call unknown) → **$0.4812**
- **maximum reserved total ≈ $1.29** (under $2)

Expected typical if usage is near published medium image tokens and modest TTS audio:

- **about $0.65–$0.90**

Hard cap: **$2.00**. Known + in-flight reserved + next reservation must stay ≤ $2 or the call is not submitted.

## Veo recovery

`GoogleVeoProvider` writes `REQUEST_SUBMITTED` with `operation_name` before polling.
Restart resumes the journal (`RESUMABLE_STATES` / `DOWNLOADABLE_STATES`).
Empty or uncertain remote status stops the canary; it does not submit again.
Worker ledger marks `SUBMITTED` with `remote_operation_id` immediately after submit.

## Commands

```bash
uv run docprod generation-canary --stage plan
uv run docprod generation-canary --stage check
uv run docprod generation-canary --stage status
# do not run until explicit resume approval:
# uv run docprod generation-canary --stage execute
```

`--stage status` is zero-network. It reconstructs paid operations from local artifacts and the ledger sidecar.

`--stage check` validates flags, key presence (not values), FFmpeg, catalog models, plan, cap, directories. Zero HTTP.

Partial paid runs must **resume**: reuse successful script/images, retry Veo only if FAILED_UNBILLED (no remote id), recover if a remote id exists, stop on UNCERTAIN.

Veo 3.1 Lite preview supports `16:9` and `9:16`. Local preflight must not mark SUBMITTED.

`--stage execute` prints:

```text
CANARY
Project: videoforge_local_canary
Duration target: ...
Scenes: ...
Images: ...
Veo: ...
Voice: gpt-4o-mini-tts
Reserved provider spend: $...
Hard cap: $2.00
Paid generation: ENABLED
Paid APIs: ENABLED
```

then runs only if every gate is set. No Y/N prompt.

## Local env (ignored `.env` only — never Vercel)

```text
GENERATION_MODE=real
REAL_GENERATION_DRY_RUN=false
ALLOW_PAID_GENERATION=true
ALLOW_PAID_APIS=true
OPENAI_API_KEY=<local>
GEMINI_API_KEY=<local>
CANARY_MAX_PROVIDER_USD=2.0
```

## Final MP4

`projects/videoforge_local_canary/artifacts/render/final/documentary_preview.mp4`

No Stars. No Neon. No Telegram payment. Isolated MemoryRepository + local disk.
