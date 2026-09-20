# Deploy VideoForge (Vercel + Railway)

Generation stays **mocked**. Paid AI stays **off**. Do **not** run `telegram-bot` polling once the production webhook is set.

## SECTION 1 — Prerequisites

1. Push this GitHub repository (same repo for Vercel and Railway).
2. Railway account.
3. Vercel account.
4. Real bot **@VideoForgeAIBot** already exists.
5. BotFather token available only in a private password manager / local ignored `.env`. Never paste it into git, Vercel frontend env, or chat logs.

Local remaining workflow (unchanged):

```bash
uv run docprod telegram-api-serve
uv run docprod telegram-worker
uv run docprod telegram-bot
cd apps/telegram-mini-app && npm run dev
```

## SECTION 2 — Railway project

1. Railway → **New Project**.
2. **Add PostgreSQL**. Copy the provided `DATABASE_URL` into a notes app (do not commit it).
3. **New Service** → **GitHub Repo** → this repository. Name it **api**.
4. **New Service** → **GitHub Repo** → **same** repository. Name it **worker**.
5. Leave worker **without** a public domain.

Both services should detect the root `Dockerfile`.

## SECTION 3 — API configuration

Set these on the **api** service (empty values mean you paste privately):

```
APP_ENV=production
PRODUCT_PERSISTENCE=postgres
DATABASE_URL=<Railway Postgres URL, usually injected>
PAYMENT_MODE=telegram
GENERATION_MODE=mock
ALLOW_PAID_GENERATION=false
ALLOW_PAID_APIS=false
TELEGRAM_BOT_TOKEN=
TELEGRAM_BOT_USERNAME=VideoForgeAIBot
TELEGRAM_MINI_APP_URL=
TELEGRAM_WEBHOOK_URL=
TELEGRAM_WEBHOOK_SECRET=
TELEGRAM_INIT_DATA_MAX_AGE_SECONDS=86400
API_SESSION_SECRET=
CORS_ALLOWED_ORIGINS=
LOG_LEVEL=INFO
```

Generate secrets locally (do not paste the output into git):

```bash
openssl rand -hex 32
```

Run twice: one value → `API_SESSION_SECRET`, one value → `TELEGRAM_WEBHOOK_SECRET`.

Reference names: `.env.production.example`.

You can fill `TELEGRAM_MINI_APP_URL`, `CORS_ALLOWED_ORIGINS`, and `TELEGRAM_WEBHOOK_URL` after Vercel and the API domain exist (Section 8).

## SECTION 4 — API deployment

In the **api** service settings:

- **Builder:** Dockerfile (repo root)
- **Start command:** `uv run docprod telegram-api-serve`
- **Custom start command** is enough; `PORT` is injected. The CLI binds `0.0.0.0:$PORT`.
- **Pre-deploy / Release command:** `uv run alembic upgrade head`
- **Healthcheck path:** `/health`
- **Healthcheck timeout:** 10s is enough

`GET /health` is liveness only (fast, no Telegram). Use `GET /ready` yourself after deploy to confirm `payment_mode`, `generation_mode`, and database.

Do **not** run the worker loop in this service.

## SECTION 5 — API domain

Railway **api** service → **Networking** → generate a public HTTPS domain.

You will later set:

```
TELEGRAM_WEBHOOK_URL=https://<api-domain>/telegram/webhook
NEXT_PUBLIC_API_BASE_URL=https://<api-domain>
```

Do not invent the hostname here.

## SECTION 6 — Worker

**worker** service:

- **Start command:** `uv run docprod telegram-worker`
- **No public domain**
- **Do not** set a pre-deploy migrate command
- Same `DATABASE_URL` as API
- Same product flags:

```
APP_ENV=production
PRODUCT_PERSISTENCE=postgres
PAYMENT_MODE=telegram
GENERATION_MODE=mock
ALLOW_PAID_GENERATION=false
ALLOW_PAID_APIS=false
TELEGRAM_BOT_TOKEN=
TELEGRAM_BOT_USERNAME=VideoForgeAIBot
TELEGRAM_MINI_APP_URL=
```

Worker does **not** need `API_SESSION_SECRET`, `TELEGRAM_WEBHOOK_SECRET`, `TELEGRAM_WEBHOOK_URL`, or `CORS_ALLOWED_ORIGINS`.

SIGTERM stops the poll loop cleanly so Railway can restart.

## SECTION 7 — Vercel

1. Vercel → **Add New** → **Project** → same GitHub repo.
2. **Root Directory:** `apps/telegram-mini-app`
3. Framework: Next.js (auto).
4. Environment variables (Production):

```
NEXT_PUBLIC_APP_ENV=production
NEXT_PUBLIC_API_BASE_URL=https://<api-domain>
```

Leave `NEXT_PUBLIC_API_BASE_URL` until Section 5 exists, then redeploy.

**Never** set on Vercel:

- `TELEGRAM_BOT_TOKEN`
- `DATABASE_URL`
- `API_SESSION_SECRET`
- `TELEGRAM_WEBHOOK_SECRET`

Deploy.

## SECTION 8 — Connect URLs

After real URLs exist:

| Value | Goes to |
| --- | --- |
| `https://<project>.vercel.app` | API `TELEGRAM_MINI_APP_URL` |
| `https://<project>.vercel.app` | API `CORS_ALLOWED_ORIGINS` (no trailing slash, no `*`) |
| `https://<api-domain>` | Vercel `NEXT_PUBLIC_API_BASE_URL` |
| `https://<api-domain>/telegram/webhook` | API `TELEGRAM_WEBHOOK_URL` |
| Vercel URL | Worker `TELEGRAM_MINI_APP_URL` (Open Project button) |

Redeploy / restart:

- Vercel: after `NEXT_PUBLIC_*` changes (rebuild required).
- Railway API: after CORS, Mini App URL, webhook URL/secret, session secret.
- Railway worker: after Mini App URL or bot token.

## SECTION 9 — Webhook

From a machine that has production API env **or** after SSH/local with production vars (never print the token):

```bash
uv run docprod telegram-webhook-set
uv run docprod telegram-webhook-info
```

`telegram-webhook-info` prints URL and pending count, not the token.

**Do not** also run `uv run docprod telegram-bot` against @VideoForgeAIBot.

## SECTION 10 — BotFather

Official Mini App docs (`core.telegram.org/bots/webapps`):

1. Open **@BotFather**.
2. `/mybots` → **VideoForgeAIBot**.
3. **Bot Settings → Configure Mini App → Enable Mini App**. Set the HTTPS Vercel URL.
4. Optionally configure the **Main Mini App** from the same BotFather bot settings so the profile can show an Open App button.
5. `/setmenubutton` **or** Bot Settings → **Menu Button**: HTTPS Mini App URL + label such as `Open Studio`.
6. If BotFather asks to link a website domain, use `/setdomain` with the **hostname only** (example: `your-app.vercel.app`), not `http://127.0.0.1`.

The bot also sends an **Open Video Studio** Web App button on `/start` once `TELEGRAM_MINI_APP_URL` is public HTTPS.

## SECTION 11 — Smoke test

1. `/start` on @VideoForgeAIBot.
2. Open Studio (menu button or inline Web App button).
3. Telegram Mini App auth (no Dev login).
4. Create a tiny project → Calculate Price.
5. Pay **one** small Stars invoice you accept losing.
6. Confirm backend `payment-status` is `PAID`.
7. Generation runs as **mock**.
8. Bot: “Your video is ready” → Open Project.

If media thumbnails 404, that is the documented ephemeral-disk limitation, not a payment failure.

## SECTION 12 — Rollback

1. Disable webhook: `uv run docprod telegram-webhook-set` is not enough by itself if URL is still set. From a token-configured shell, polling startup calls `deleteWebhook`. Safer: Railway **api** service → remove/stop it, then locally:

   ```bash
   uv run docprod telegram-bot
   ```

   That command **refuses** `APP_ENV=production`. Use local `.env` with `APP_ENV=development` to poll again.

2. Stop Railway **api** and **worker**.
3. Do not send more Stars invoices.
4. Keep `PAYMENT_MODE=simulated` locally; do not point the production Mini App at localhost.

## Healthcheck choice

Railway should probe **`GET /health`**. It does not call Telegram. `GET /ready` is for you after deploy (503 if Postgres is down).

## Mock media limitation

Worker and API do not share a disk. Mock `/media` bytes may disappear on restart or fail across services until object storage exists. Quotes, payments, jobs, and Telegram notifications use Postgres and remain authoritative.
