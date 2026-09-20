# Local Telegram Mini App development (Phase 13C/13D)

No paid AI, Stars, or Telegram Bot API calls.

## PostgreSQL only (Compose)

```bash
docker compose up -d postgres
export PRODUCT_PERSISTENCE=postgres
export DATABASE_URL=postgresql+psycopg://docprod:docprod@127.0.0.1:5432/docprod
uv run alembic upgrade head
uv run docprod telegram-api-seed
```

Terminal 1:

```bash
uv run docprod telegram-api-serve
```

Terminal 2:

```bash
uv run docprod telegram-worker
```

API: `http://127.0.0.1:8000/docs`  
Health: `GET /health` (no credentials)  
Ready: `GET /ready`

## JSON mode (no Docker)

```bash
export PRODUCT_PERSISTENCE=json
uv run docprod telegram-api-seed --store product_data/store.json
uv run docprod telegram-api-serve
```

Generation in JSON/test mode can still be driven with
`POST /api/v1/dev/jobs/{id}/run`. Postgres mode expects `telegram-worker`.

## Mini App frontend

Terminal 3:

```bash
cd apps/telegram-mini-app
cp .env.example .env.local
npm install
npm run dev
```

Open http://127.0.0.1:3000 — use **Dev login**. The amber banner means
simulated Stars and mock generation. Do not confuse this with production auth.

Optional CORS is enabled for `http://127.0.0.1:3000`. Next also reverse-proxies
`/api/*` to `http://127.0.0.1:8000`.


## Simulated payment

Development/test only:

`POST /api/v1/dev/payments/{quote_id}/confirm`

Disabled when `APP_ENV` is not `development` or `test`.

## JSON import

See `docs/DATABASE_OPERATIONS.md`. Engine artifacts are not imported.
