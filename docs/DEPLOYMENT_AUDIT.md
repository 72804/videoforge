# Deployment audit (Phase 15.5)

Prepared for Vercel Mini App + Railway API/worker/Postgres. Generation stays mocked.

## Already works

- FastAPI factory: `uv run docprod telegram-api-serve` (`--host`, `--port`; `PORT` binds `0.0.0.0`)
- Worker: `uv run docprod telegram-worker` (no public HTTP loop)
- Local polling: `uv run docprod telegram-bot` (refuses `APP_ENV=production`)
- Webhook: `POST /telegram/webhook` + `uv run docprod telegram-webhook-set` / `telegram-webhook-info`
- Health: `GET /health` (liveness), `GET /ready` (DB + modes, no Telegram call)
- Alembic: `uv run alembic upgrade head` via `DATABASE_URL`
- Postgres: `PRODUCT_PERSISTENCE=postgres` + SQLAlchemy/psycopg (Railway `postgres://` normalized)
- CORS: `CORS_ALLOWED_ORIGINS` / `API_CORS_ORIGINS`
- Mini App: `apps/telegram-mini-app` (`npm run build`)
- Production validation for mock generation and disabled paid APIs
- Secrets ignored: `.env`, `.env.*` (except committed examples)

## Needs operator setup (not automated here)

- GitHub repo, Railway project + Postgres, Vercel project
- Public HTTPS Mini App and API domains
- BotFather Mini App / menu button / domain
- Telegram webhook after API domain exists
- `API_SESSION_SECRET` and `TELEGRAM_WEBHOOK_SECRET` generated privately

## Gaps documented, not solved in 15.5

- Mock asset bytes use `LocalStorageBackend` on ephemeral disk and are **not shared** between API and worker containers. Job status and bot notifications still work; `/media` thumbnails may 404 after restart or across services. Object storage is later.
- No Redis. No R2/S3. No paid providers.
- No existing Docker/compose/Vercel/Railway config before this phase (Dockerfile added).
