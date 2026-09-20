# Telegram production audit (Phase 15)

Scope: Mini App identity, bot, Stars invoices, mock generation. Paid Veo/OpenAI/Runway remain **off**.

## Production-ready

- Server-side HMAC validation of Mini App `initData` (`WebAppData` secret, `auth_date` max age, required `user.id`).
- Application session after upsert of `TelegramUser` keyed by `telegram_user_id`.
- Username / display name stored as mutable metadata only.
- `PAYMENT_MODE=telegram` invoice path: `createInvoiceLink` with currency `XTR`, empty `provider_token`, amount = server `StarQuote.stars`.
- Opaque `PaymentIntent.id` as Telegram invoice payload (≤128 bytes).
- `pre_checkout_query` re-validates user, quote, plan hash, currency, Stars amount, expiry.
- `successful_payment` uses `telegram_payment_charge_id` uniqueness; duplicate updates no-op.
- `GET /api/v1/quotes/{id}/payment-status` customer states only.
- Webhook `POST /telegram/webhook` with `X-Telegram-Bot-Api-Secret-Token`.
- Production startup fails if simulated payment, missing bot token, non-https Mini App URL, missing session secret, missing webhook secret, `GENERATION_MODE!=mock`, or `ALLOW_PAID_GENERATION=true`.
- Mock generation worker refuses paid provider execution.
- Notification outbox → bot messages without provider error text.

## Mock / development-only

- `POST /api/v1/dev/auth` and `POST /api/v1/dev/payments/{quote_id}/confirm` (and `dev/jobs/{id}/run`) when `APP_ENV` is `development` or `test`.
- `PAYMENT_MODE=simulated` (local) and `PAYMENT_MODE=fake` (automated tests with `FakeTelegramClient`).
- Mini App **Dev login** and **Simulated payment** banner when `NEXT_PUBLIC_APP_ENV=development`.
- Generation always mock in this phase (`GENERATION_MODE=mock`).

## Missing (intentionally later)

- Real Veo / OpenAI / Runway / TTS / music (Phase 16).
- Automated Stars refund policy and operator refund UI.
- Backend persistence of appearance preference (localStorage only).
- Prepaid Stars wallet (mechanism B).
- Direct Mini App `startapp` routing beyond path URLs Telegram currently supports on WebApp buttons.

## Unsafe if misconfigured

- Running production with `PAYMENT_MODE=simulated` (blocked at startup).
- Trusting `initDataUnsafe` or client `telegram_user_id` (not used as authority).
- Accepting webhook updates without `TELEGRAM_WEBHOOK_SECRET`.
- Running polling (`docprod telegram-bot`) and a webhook on the same bot at once.
- Exposing `TELEGRAM_BOT_TOKEN` or webhook secret to the Mini App (`NEXT_PUBLIC_*` must never include them).
