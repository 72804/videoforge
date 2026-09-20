# Deployment audit

Production target: **one Vercel project** (Next.js + FastAPI Services) + **Neon PostgreSQL**. Generation stays mocked.

Existing public domain: `https://videoforge-dusky.vercel.app`

## Already works

- Vercel Services: `frontend` = `apps/telegram-mini-app`, `backend` = `services/api` (`app.py` → `app_from_settings()`)
- Local API: `uv run docprod telegram-api-serve`
- Local worker: `uv run docprod telegram-worker` (not used on Vercel)
- Bounded mock jobs: inline generate + `POST /internal/jobs/run`
- Local polling: `uv run docprod telegram-bot` (refuses `APP_ENV=production`)
- Webhook: `POST /telegram/webhook` on the same public domain
- Health: `GET /health`, `GET /ready`
- Alembic: `uv run alembic upgrade head` or `uv run docprod telegram-migrate`
- Postgres: Neon pooled URL + NullPool in production
- Mini App same-origin `/api/v1/*`
- Production flags: mock generation, paid APIs off

## Operator setup (existing Vercel project)

- Root Directory = repository root
- Framework Preset = Services
- Neon `DATABASE_URL` + secrets on that project
- BotFather + webhook on `https://videoforge-dusky.vercel.app`

## Known limits this phase

- Production mock bytes are placeholders. Object storage is next before real generation.
- No Redis. No R2/S3. No paid providers. No second Vercel project.
