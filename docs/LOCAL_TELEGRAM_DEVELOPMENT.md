# Local Telegram Mini App development

Ordinary local work does **not** need a Telegram bot, webhook, or Stars.

Defaults:

- `APP_ENV=development`
- `PAYMENT_MODE=simulated`
- `GENERATION_MODE=mock`
- `ALLOW_PAID_GENERATION=false`

Frontend: `NEXT_PUBLIC_APP_ENV=development` enables Dev login and simulated Stars.

## PostgreSQL (Compose)

```bash
docker compose up -d postgres
export PRODUCT_PERSISTENCE=postgres
export DATABASE_URL=postgresql+psycopg://docprod:docprod@127.0.0.1:5432/docprod
uv run alembic upgrade head
uv run docprod telegram-api-seed
```

Terminal 1: `uv run docprod telegram-api-serve`  
Terminal 2: `uv run docprod telegram-worker`  
Terminal 3: Mini App:

```bash
cd apps/telegram-mini-app
cp .env.example .env.local
npm install
npm run dev
```

Open http://127.0.0.1:3000 — **Dev login**. Amber banner = simulated Stars + mock generation.

API: `http://127.0.0.1:8000/docs`  
Health: `GET /health`  
Ready: `GET /ready`

JSON mode: `PRODUCT_PERSISTENCE=json` and `POST /api/v1/dev/jobs/{id}/run` after generate.

Simulated payment (development/test only): `POST /api/v1/dev/payments/{quote_id}/confirm`.

JSON import: `docs/DATABASE_OPERATIONS.md`.

## Optional: real bot against a tunnel

Keep generation mock. Set `PAYMENT_MODE=telegram`, `TELEGRAM_BOT_TOKEN`, https Mini App URL (tunnel), `TELEGRAM_WEBHOOK_URL`, `TELEGRAM_WEBHOOK_SECRET`.

```bash
uv run docprod telegram-webhook-set
uv run docprod telegram-webhook-info
```

**or** local polling (clears webhook):

```bash
uv run docprod telegram-bot
```

Never run webhook and polling together.

## Environment (server)

| Variable | Notes |
| --- | --- |
| `APP_ENV` | `development` / `test` / `production` |
| `TELEGRAM_BOT_TOKEN` | Server only |
| `TELEGRAM_MINI_APP_URL` | https in production |
| `TELEGRAM_WEBHOOK_URL` | `https://host/telegram/webhook` |
| `TELEGRAM_WEBHOOK_SECRET` | Required in production |
| `TELEGRAM_INIT_DATA_MAX_AGE_SECONDS` | Default 86400 |
| `PAYMENT_MODE` | `simulated` (dev) / `telegram` (prod) / `fake` (tests) |
| `GENERATION_MODE` | `mock` |
| `ALLOW_PAID_GENERATION` | `false` |
| `API_SESSION_SECRET` | Required in production |
| `DATABASE_URL` | Postgres |
| `PRODUCT_PERSISTENCE` | `json` or `postgres` |

Frontend public only: `NEXT_PUBLIC_API_BASE_URL`, `NEXT_PUBLIC_APP_ENV`.
