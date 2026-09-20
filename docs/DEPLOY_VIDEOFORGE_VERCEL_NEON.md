# Deploy VideoForge (Vercel + Neon)

Production target is **two Vercel projects** from the same GitHub repo plus **Neon PostgreSQL**.
Generation stays **mocked**. Paid AI stays **off**. Do **not** run `telegram-bot` polling once the production webhook is set.

A single Vercel project would mix Next.js and FastAPI roots. That is not simpler here: keep Mini App `Root Directory = apps/telegram-mini-app` and the API at the **repository root**.

Repo: `https://github.com/72804/videoforge.git`

The FastAPI app is a Vercel Python **framework preset** entrypoint (`api/index.py` → `app`). There is no Node proxy. Routes stay `/health`, `/ready`, `/telegram/webhook`, `/api/v1/*`.

## Human checklist

1. Create a Neon project (region close to Vercel).
2. Copy the **pooled** `DATABASE_URL` into a password manager (hostname contains `-pooler.`). Never commit it. Never put it on the Mini App.
3. Run the Alembic migration **once** against Neon (not on every request):

```bash
export DATABASE_URL='postgresql://USER:PASSWORD@HOST-pooler.REGION.aws.neon.tech/neondb?sslmode=require'
uv run alembic upgrade head
```

Equivalent:

```bash
export DATABASE_URL='...'
uv run docprod telegram-migrate
```

4. Vercel → **Add New** → **Project** → import `72804/videoforge`. Name it **VideoForge API**. **Root Directory: repository root** (leave empty / `.`). Framework: FastAPI / Python.
5. Set API environment variables (Section “API env”). Deploy.
6. Open `https://<api-vercel-domain>/health` then `/ready`. Expect `generation_mode=mock`, `payment_mode=telegram`, database ready.
7. Vercel → **Add New** → **Project** → same repo. Name it **VideoForge Mini App**. **Root Directory: `apps/telegram-mini-app`**.
8. Mini App env:

```
NEXT_PUBLIC_APP_ENV=production
NEXT_PUBLIC_API_BASE_URL=https://<api-vercel-domain>
```

Must be public `https://`. Localhost is rejected at production build.
9. Deploy the Mini App. Copy its origin, e.g. `https://<mini-app-domain>`.
10. On the **API** project set:

```
TELEGRAM_MINI_APP_URL=https://<mini-app-domain>
CORS_ALLOWED_ORIGINS=https://<mini-app-domain>
TELEGRAM_WEBHOOK_URL=https://<api-vercel-domain>/telegram/webhook
```

11. Redeploy the **API** after those URL env changes.
12. From a machine that has the bot token in a local ignored `.env` (never paste the token into chat or git):

```bash
uv run docprod telegram-webhook-set
uv run docprod telegram-webhook-info
```

13. BotFather: Menu Button / Mini App URL = `https://<mini-app-domain>`. Configure domain.
14. Telegram: `/start` on `@VideoForgeAIBot` → Open Studio → Telegram auth → quote → **one** controlled Stars payment → mock generation → completion notification.

Do **not** enable `ALLOW_PAID_GENERATION` or `ALLOW_PAID_APIS`. Do **not** connect Veo / OpenAI / Runway / ElevenLabs.

## Why two Vercel projects

| Project | Root | Runtime |
|---|---|---|
| VideoForge Mini App | `apps/telegram-mini-app` | Next.js |
| VideoForge API | repository root | Python FastAPI (`api/index.py`) |

Frontend never receives `DATABASE_URL`, bot token, session secret, webhook secret, or `INTERNAL_JOB_SECRET`.

## Mock jobs without a permanent worker

Vercel Functions do not run `uv run docprod telegram-worker` forever.

Production default: `JOB_EXECUTION_MODE=inline`.

1. Client calls generate (after Stars confirmation in Neon).
2. API persists a `GenerationJob` and claims it by **server-generated** job id.
3. The same bounded invocation runs mock stages, writes outbox rows, and attempts Telegram delivery.
4. The function returns. No `while True`.

Crash recovery: `POST /internal/jobs/run` with header `X-Internal-Job-Secret`. It runs **at most one** queued job (`run_bounded(max_jobs=1)`). Expired leases can be reclaimed. Terminal jobs are no-ops. Duplicate payments stay unique in the ledger.

Local development still uses:

```bash
uv run docprod telegram-api-serve
uv run docprod telegram-worker
uv run docprod telegram-bot
```

`telegram-bot` polling refuses `APP_ENV=production`.

Optional one-shot local drain: `uv run docprod telegram-jobs-run --max-jobs 1`.

## File storage

Production PostgreSQL uses `PlaceholderStorageBackend`. Mock asset **metadata** is in Neon. Bytes are **not** durable. `GET /api/v1/media/{id}` returns 404. Object storage (S3/R2) is a later phase before real media.

## API env (Vercel API project)

```
APP_ENV=production
PRODUCT_PERSISTENCE=postgres
DATABASE_URL=
API_SESSION_SECRET=
INTERNAL_JOB_SECRET=
PAYMENT_MODE=telegram
GENERATION_MODE=mock
ALLOW_PAID_GENERATION=false
ALLOW_PAID_APIS=false
JOB_EXECUTION_MODE=inline
TELEGRAM_BOT_TOKEN=
TELEGRAM_BOT_USERNAME=VideoForgeAIBot
TELEGRAM_MINI_APP_URL=
TELEGRAM_WEBHOOK_URL=
TELEGRAM_WEBHOOK_SECRET=
TELEGRAM_INIT_DATA_MAX_AGE_SECONDS=86400
CORS_ALLOWED_ORIGINS=
LOG_LEVEL=INFO
JOB_LEASE_SECONDS=30
```

Generate secrets locally (do not paste output into git):

```bash
openssl rand -hex 32
```

Use three values: `API_SESSION_SECRET`, `TELEGRAM_WEBHOOK_SECRET`, `INTERNAL_JOB_SECRET`.

No secret uses a `NEXT_PUBLIC_` prefix.

Webhook URL shape: `https://<api-vercel-domain>/telegram/webhook`.

## Frontend env (Vercel Mini App project)

```
NEXT_PUBLIC_APP_ENV=production
NEXT_PUBLIC_API_BASE_URL=https://<api-vercel-domain>
```

## Database connections

Production and Neon pooled URLs use SQLAlchemy `NullPool` (no large per-instance pool). `postgres://` is rewritten to `postgresql+psycopg://`. Query strings such as `sslmode=require` are preserved. Local Compose Postgres tests keep a normal pool unless the URL contains `-pooler.` or `pgbouncer=true`.

Migrations are **never** run inside a request handler.

## Python install on Vercel

Vercel reads `pyproject.toml` (`requires-python >= 3.12`, `.python-version` is `3.12`). It does not need `uv run`. Optional Google extras are not required. Real FFmpeg rendering is not used in this mock phase.

`Dockerfile` remains for a **future dedicated worker host**. The Vercel API does not use it.

## BotFather

1. Open `@BotFather` → your bot `@VideoForgeAIBot`.
2. Set Menu Button / Mini App to the **frontend** HTTPS URL.
3. Add the Mini App domain.
4. Do not put the API URL in the menu button.

## After deploy, one Stars payment

Use a real Telegram account you control. Quote first. Pay once. Confirm the bot message. Do not loop payments while debugging.

## Railway / Docker (superseded for production)

See [DEPLOY_VIDEOFORGE.md](DEPLOY_VIDEOFORGE.md). That path is optional if you later host a long-running worker. It is **not** required for this Vercel + Neon mock phase.
