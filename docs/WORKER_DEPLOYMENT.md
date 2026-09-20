# Worker deployment (Cloud Run Jobs)

Do not run FFmpeg, Veo polling, or paid image/TTS calls on Vercel.

## Image

Use the repository `Dockerfile` (Python 3.12 + FFmpeg + `uv`). Override the command:

```text
uv run docprod telegram-worker-once
```

That command claims at most one queued job and exits (scale-to-zero).

Optional long poll for a staging VM:

```text
uv run docprod telegram-worker
```

## Google Cloud Run Job (first canary)

1. Build and push the image to Artifact Registry.
2. Create a Cloud Run **Job** (not a Service) with:
   - CPU 1–2, memory 2Gi
   - task timeout ≥ 60 minutes
   - max retries 0 (application recovers remotes; do not double-start paid work)
3. Worker env (never copy provider keys to Vercel):

```text
APP_ENV=production
PRODUCT_PERSISTENCE=postgres
DATABASE_URL=...                  # Neon; same DB as API
GENERATION_MODE=real
REAL_GENERATION_DRY_RUN=true      # keep true until the canary review
ALLOW_PAID_GENERATION=false
ALLOW_PAID_APIS=false
PAYMENT_MODE=telegram
TELEGRAM_BOT_TOKEN=...            # send completion only
TELEGRAM_MINI_APP_URL=https://videoforge-dusky.vercel.app
S3_BUCKET=...
S3_ENDPOINT=https://<accountid>.r2.cloudflarestorage.com
S3_REGION=auto
S3_ACCESS_KEY=...
S3_SECRET_KEY=...
WORKER_ID=cloudrun-canary
JOB_LEASE_SECONDS=120
```

4. Wake from Vercel after queue (optional): HTTP target that executes the Job (`WORKER_WAKE_URL` on the API). If unset, run the Job manually / on a Cloud Scheduler `* * * * *` with a 1-task execute.

## Vercel API when a worker exists

```text
JOB_EXECUTION_MODE=worker
WORKER_WAKE_URL=https://...       # optional job execute URL
GENERATION_MODE=mock              # API must stay mock
ALLOW_PAID_GENERATION=false
ALLOW_PAID_APIS=false
# no OPENAI_API_KEY / GEMINI_API_KEY / RUNWAY / ELEVENLABS
```

Until `JOB_EXECUTION_MODE=worker`, production still runs the **mock** inline worker (current live behavior).

## Cost at near-zero traffic

Idle Cloud Run Job: $0. One 15–30s canary: a few cents of CPU/RAM plus provider USD (see canary doc). R2 storage is billed on GB stored + Class A writes; no egress to Cloudflare-connected clients.

## Local

```text
GENERATION_MODE=real
REAL_GENERATION_DRY_RUN=true
uv run docprod telegram-jobs-run --max-jobs 1
```

No provider keys required.
