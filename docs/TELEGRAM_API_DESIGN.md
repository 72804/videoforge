# Telegram backend API (design only — not served in 13A)

All routes require validated Mini App initData except the Bot payment webhook.

Auth header (proposed): `X-Telegram-Init-Data`.

## Auth

`POST /api/auth/telegram`  
Body: `{ "initData": "..." }` → `TelegramUser` (server-validated).

## Projects

`POST /api/projects` create  
`GET /api/projects` list for current user  
`GET /api/projects/{id}` `ProjectSummary`  
`PATCH /api/projects/{id}` update settings (invalidates quote)

## Characters

`POST /api/projects/{id}/characters`  
`POST /api/projects/{id}/characters/{cid}/references` multipart image

## Plan / quote / generate

`POST /api/projects/{id}/plan` → `GenerationPlan`  
`POST /api/projects/{id}/quote` → `StarQuote` `{ stars, expires_at, quote_hash }`  
`POST /api/projects/{id}/generate` `{ quote_id }` → `{ job_id }`  
Requires server-confirmed payment for that quote.

## Jobs

`GET /api/jobs/{id}` work-unit progress (not fake percentages)

## Scenes

`GET /api/projects/{id}/scenes` → `[SceneSummary]`  
`PATCH /api/scenes/{id}` prompt/motion/duration/models/characters  
`POST /api/scenes/{id}/regenerate-image`  
`POST /api/scenes/{id}/regenerate-video`  
`POST /api/scenes/{id}/duplicate`  
`POST /api/projects/{id}/scenes/reorder`

## Render / export

`POST /api/projects/{id}/render`

## Payments (bot)

`POST /api/payments/telegram/update`  
Idempotent on `telegram_payment_id`. Never trust Mini App `payment_success`.

## Mini App payloads

Keep responses small: `ProjectSummary`, `SceneSummary`, `JobStatusView`.
Do not send engine manifests, provider keys, or raw Veo operation names.
