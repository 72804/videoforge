# Deployment audit

Production target: **Vercel Mini App + Vercel FastAPI + Neon PostgreSQL**. Generation stays mocked.

Railway + Docker worker from Phase 15.5 is **optional / superseded** for production. Dockerfile remains for a future dedicated worker.

## Already works

- FastAPI factory: `uv run docprod telegram-api-serve`; Vercel entrypoint `app.py` → `app_from_settings()` (FastAPI framework preset, not `api/index.py`)
- Local worker: `uv run docprod telegram-worker` (not used on Vercel)
- Bounded mock jobs: inline generate path + `POST /internal/jobs/run` + `telegram-jobs-run`
- Local polling: `uv run docprod telegram-bot` (refuses `APP_ENV=production`)
- Webhook: `POST /telegram/webhook` + `telegram-webhook-set` / `telegram-webhook-info`
- Health: `GET /health`, `GET /ready`
- Alembic: `uv run alembic upgrade head` or `uv run docprod telegram-migrate` (explicit, not per request)
- Postgres: `PRODUCT_PERSISTENCE=postgres` + SQLAlchemy/psycopg (Neon `postgres://` and pooled `-pooler.` URLs)
- CORS: `CORS_ALLOWED_ORIGINS` exact origins
- Mini App: `apps/telegram-mini-app`
- Production flags: mock generation, paid APIs off
- Secrets ignored: `.env`, `.env.*` (except committed examples)

## Operator setup (not automated)

- Neon project + private `DATABASE_URL`
- Two Vercel projects from `72804/videoforge`
- Public HTTPS Mini App and API domains
- BotFather Mini App / menu button / domain
- Telegram webhook after API domain exists
- `API_SESSION_SECRET`, `TELEGRAM_WEBHOOK_SECRET`, `INTERNAL_JOB_SECRET` generated privately

## Known limits this phase

- Production mock bytes are placeholders. `/media` does not imply durable disk. Object storage is next before real generation.
- No Redis. No R2/S3. No paid providers.
- No infinite worker on Vercel.
