# First real generation canary

Do **not** enable paid APIs until this checklist is reviewed.

Goal: one short fictional video, real Stars, strict USD cap, inspect result, then expand. Reliability over cinema.

## Size

- 15–30 seconds (AUTO = 24s, 3 scenes)
- 2–5 scenes
- ≤ 1 Veo shot
- `CANARY_MAX_PROVIDER_USD=2.0`

## Allowlist

Set `GENERATION_CANARY_TELEGRAM_IDS` to numeric Telegram user ids (comma-separated). **Never commit an id.** `REAL_GENERATION_CANARY=true` rejects everyone else at authorize.

## Dry run first (this phase)

Worker:

```text
GENERATION_MODE=real
REAL_GENERATION_DRY_RUN=true
ALLOW_PAID_GENERATION=false
ALLOW_PAID_APIS=false
```

Produces a complete job graph, R2 (or fake) final, and Telegram-ready outbox with **0 provider HTTP**.

## Manual enablement for ONE live job (after review)

1. Confirm OpenAI image/TTS and Veo 3.1 Lite are still available at catalog prices.
2. `alembic` / `docprod telegram-migrate` includes `20260920_0003`.
3. R2 bucket + CORS + worker + API `JOB_EXECUTION_MODE=worker`.
4. Worker only:

```text
REAL_GENERATION_DRY_RUN=false
ALLOW_PAID_GENERATION=true
ALLOW_PAID_APIS=true
OPENAI_API_KEY=...
GEMINI_API_KEY=...          # Veo
REAL_GENERATION_CANARY=true
GENERATION_CANARY_TELEGRAM_IDS=<your numeric id>
CANARY_MAX_PROVIDER_USD=2.0
```

5. Vercel still has **no** provider keys, `GENERATION_MODE=mock`, `ALLOW_PAID_*=false`.
6. Pay real Stars in the Mini App for a 15–30s CUSTOM_STORY project with uploaded character refs.
7. Inspect Neon attempts, R2 objects, signed playback, Telegram “Your video is ready 🎬”.
8. Set `ALLOW_PAID_*=false` and `REAL_GENERATION_DRY_RUN=true` again if anything looks wrong.

Estimated provider USD for the first 24s / 3 stills / 1×8s Veo / TTS (catalog, **verify live**): **about $0.55–$0.90**, well under $2. Cloud Run CPU for one job: cents. Stars charged follow the frozen quote, not provider overage.

Paid provider calls during Phase 16 implementation: **0**.
