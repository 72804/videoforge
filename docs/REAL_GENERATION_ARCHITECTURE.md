# Real generation architecture

VideoForge stays a Telegram Mini App on Vercel. Real AI video generation does **not** run inside a Vercel request. The existing documentary/drama engine is reused through a product adapter. Paid provider keys never live on Vercel.

## Recommendation: Google Cloud Run Jobs + Cloudflare R2

| Option | Idle cost | Max time | FFmpeg | Verdict |
| --- | --- | --- | --- | --- |
| Vercel request / Fluid | low | too short for Veo poll + FFmpeg | no | orchestration only |
| Vercel Queues / Workflow | low | better for HTTP fan-out, not FFmpeg containers | no | not the renderer |
| GitHub Actions | free-ish | not a production job runner, no private secrets isolation for customer jobs | possible | reject |
| Railway always-on | billed while idle | long | yes | too expensive at near-zero traffic |
| Render background worker | similar idle bill | long | yes | same issue |
| Cheap VPS | ~$5/mo idle | unlimited | yes | simple but always on |
| Fly Machines | scale-to-zero | long | yes | viable; more ops than Cloud Run for one job |
| **Google Cloud Run Jobs** | **~$0 idle** | **up to 24h** | **yes (this repo `Dockerfile`)** | **chosen** |

Cloud Run Jobs start a container, run `docprod telegram-worker-once`, claim one Neon row (`FOR UPDATE SKIP LOCKED`), execute, exit. No replica sits warm. Cold start is acceptable for a paid 15–30s canary. Outbound HTTPS to OpenAI/Veo, R2, Neon, and Telegram all work.

Vercel remains: Mini App, FastAPI, Telegram webhook, Stars, quote/authorize, job insert, signed media redirect, notification trigger.

## Modes

- `GENERATION_MODE=mock` — Vercel API and local tests. `MockGenerationWorker` only.
- `GENERATION_MODE=real` — **worker only**. `RealGenerationWorker` maps product → engine.
- `REAL_GENERATION_DRY_RUN=true` (default) — persist script/scenes/assets/render with local fake bytes. **Zero paid HTTP.**
- Live providers require worker `ALLOW_PAID_GENERATION=true` **and** `ALLOW_PAID_APIS=true` **and** `REAL_GENERATION_DRY_RUN=false`. Live path is still gated until explicit enablement.

## Product → engine

`engine_bridge.py` maps Mini App `Project` / `Character` / `CharacterReference` onto `CharacterReferenceSet` + semantic scenes + frozen `GenerationPlan` items. Content kind is `CUSTOM_STORY` (no documentary web research). Documentary CLI pipelines (Maple, Birko V1/V2) are unchanged.

Pipeline (canary): prompt → script → scenes → stills → at most one Veo shot → TTS → procedural music/SFX → FFmpeg → R2 upload → outbox “Your video is ready 🎬”.

## Quality routing

Economy / Balanced / Premium reuse Phase 12 `wants_video` / `preferred_video_model`. Static cinematic shots stay still + local motion. Video is exceptional. Canary caps video shots at 1.

## Jobs

Payment authorizes a `GenerationJob` in Neon. Worker claims with lease + heartbeat. Crash recovery polls `remote_operation_id`; it does not submit a second paid request. Work units: Story, Scene planning, Images, Video, Voice, Audio, Render, Upload.

## Secrets

| Surface | Allowed |
| --- | --- |
| Frontend | none |
| Vercel API | Telegram, session, webhook, Neon, R2 read/sign, `INTERNAL_JOB_SECRET` |
| Worker | Neon, R2, provider keys, Telegram send |

See `WORKER_DEPLOYMENT.md`, `OBJECT_STORAGE.md`, `PROVIDER_COST_SAFETY.md`, `FIRST_REAL_GENERATION_CANARY.md`.
