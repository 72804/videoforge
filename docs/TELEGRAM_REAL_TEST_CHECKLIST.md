# Real Telegram test checklist (Phase 15)

Do **not** run this from CI. Do **not** spend Stars until you intend a single controlled payment. Generation stays mock.

## BotFather / Mini App

1. Create a bot. Copy the token into server env `TELEGRAM_BOT_TOKEN` only (never frontend, never git).
2. Set commands: `/start`, `/help`.
3. Configure the Mini App / Web App URL to an **https** origin (`TELEGRAM_MINI_APP_URL`). Localhost is not a production Mini App URL.
4. Enable payments / Stars for the bot as required by current Telegram BotFather payment settings.

## Server

```
APP_ENV=production
PAYMENT_MODE=telegram
GENERATION_MODE=mock
ALLOW_PAID_GENERATION=false
ALLOW_PAID_APIS=false
TELEGRAM_BOT_TOKEN=...
TELEGRAM_MINI_APP_URL=https://...
TELEGRAM_WEBHOOK_URL=https://.../telegram/webhook
TELEGRAM_WEBHOOK_SECRET=...
TELEGRAM_INIT_DATA_MAX_AGE_SECONDS=86400
API_SESSION_SECRET=...
DATABASE_URL=...
PRODUCT_PERSISTENCE=postgres
```

Frontend production build:

```
NEXT_PUBLIC_APP_ENV=production
NEXT_PUBLIC_API_BASE_URL=https://api.example
```

Migrate: `uv run alembic upgrade head`.

Set webhook (does not print the bot token):

```
uv run docprod telegram-webhook-set
uv run docprod telegram-webhook-info
```

Do **not** also run `uv run docprod telegram-bot` against the same bot.

Confirm `/ready` shows `payment_mode=telegram`, `generation_mode=mock`, `allow_paid_generation=false`.

## Manual path

1. Open the bot → `/start` → **Open Video Studio**.
2. Mini App authenticates (no Dev login).
3. Create a tiny project, calculate price, confirm Stars amount matches the quote card.
4. **Pay with Telegram Stars** → Telegram invoice UI.
5. Pay **one** small invoice you accept losing (this is real Stars).
6. Confirm API `payment-status` is `PAID` even if you kill the Mini App mid-callback.
7. Start generation. Worker must complete with **mock** assets. No Veo/OpenAI/Runway logs.
8. Receive “Your video is ready” (or failure copy) with **Open Project**.
9. Appearance: Settings → Dark (default), Light, System.

If anything charges providers or a second Stars debit appears for one invoice, stop and inspect ledger uniqueness.
