# Deploy VideoForge (one Vercel project + Neon)

One GitHub repo. **One Vercel project.** One public domain. Neon PostgreSQL.

Existing project: `https://videoforge-dusky.vercel.app`

Do **not** create a second Vercel project. Generation stays **mocked**. Paid AI stays **off**.

## Architecture

Vercel **Services** in repo-root `vercel.json`:

| Service | Root | Framework | Entrypoint |
|---|---|---|---|
| `frontend` | `apps/telegram-mini-app` | Next.js | default |
| `backend` | `services/api` | FastAPI | `app:app` → `app_from_settings()` |

`services/api` is a thin deploy root. It imports `docprod` from `src/`; it does not copy the backend.

## Public routing

First matching rewrite wins. Backend paths are listed **before** the frontend catch-all.

| Path | Service |
|---|---|
| `/health`, `/ready` | FastAPI |
| `/telegram/webhook` | FastAPI |
| `/internal/*` | FastAPI |
| `/api/v1/*` | FastAPI |
| `/docs`, `/openapi.json` | FastAPI |
| `/`, `/create/*`, `/projects/*`, `/settings`, everything else | Next.js |

The FastAPI app still sees the original paths (`/health`, `/api/v1/...`). There is no `/api/health` and no `/api/api/v1`.

## Same-origin Mini App

Production browser calls are relative: `/api/v1/...`.

Leave `NEXT_PUBLIC_API_BASE_URL` **empty**. Do not point it at a second hostname.

## Human checklist (existing dusky project)

1. Neon project + pooled `DATABASE_URL` in a password manager.
2. Migrate once: `DATABASE_URL='…' uv run alembic upgrade head`
3. Push this commit to `72804/videoforge` `main`.
4. In the **existing** Vercel project (dusky):
   - **Root Directory:** empty / `.` (repository root). If it is still `apps/telegram-mini-app`, change it so this `vercel.json` is used.
   - **Framework Preset:** **Services** (not Next.js-only, not FastAPI-only).
5. Set env vars on that same project (server + `NEXT_PUBLIC_APP_ENV`). Redeploy.
6. Check:
   - `https://videoforge-dusky.vercel.app/` Mini App
   - `https://videoforge-dusky.vercel.app/health`
   - `https://videoforge-dusky.vercel.app/ready`
7. `TELEGRAM_MINI_APP_URL=https://videoforge-dusky.vercel.app`
8. `TELEGRAM_WEBHOOK_URL=https://videoforge-dusky.vercel.app/telegram/webhook`
9. Redeploy after URL env changes, then:

```bash
uv run docprod telegram-webhook-set
uv run docprod telegram-webhook-info
```

10. BotFather Mini App / menu button / domain = `https://videoforge-dusky.vercel.app`
11. Telegram `/start` → Studio → auth → quote → **one** Stars payment → mock generation.

## Env (one project)

Server (never `NEXT_PUBLIC_`):

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
TELEGRAM_MINI_APP_URL=https://videoforge-dusky.vercel.app
TELEGRAM_WEBHOOK_URL=https://videoforge-dusky.vercel.app/telegram/webhook
TELEGRAM_WEBHOOK_SECRET=
TELEGRAM_INIT_DATA_MAX_AGE_SECONDS=86400
CORS_ALLOWED_ORIGINS=
LOG_LEVEL=INFO
JOB_LEASE_SECONDS=30
```

Browser:

```
NEXT_PUBLIC_APP_ENV=production
NEXT_PUBLIC_API_BASE_URL=
```

Same-origin production does not need CORS. Wildcard CORS is still forbidden. Local split-dev may set `CORS_ALLOWED_ORIGINS=http://127.0.0.1:3000,http://localhost:3000` on the API process only.

## Local development

Standalone (unchanged):

```bash
uv run docprod telegram-api-serve
uv run docprod telegram-worker
cd apps/telegram-mini-app && npm run dev
```

Dev Next.js rewrites `/api/*`, `/health`, `/ready`, `/telegram/*`, `/internal/*`, and `/docs` to `http://127.0.0.1:8000`.

Optional one-origin:

```bash
vercel dev
```

## Storage / jobs / Neon

Unchanged: Neon + NullPool, placeholder mock bytes, inline mock jobs, no paid AI, no R2/S3.
