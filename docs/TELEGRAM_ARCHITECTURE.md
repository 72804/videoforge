# Telegram architecture (Phase 13A)

```
Telegram user
   ├─ Mini App (WebApp) ── HTTPS ──► Backend API
   │                                      │
   │                                      ├─ ProductService (auth, projects, quotes)
   │                                      ├─ Generation queue / workers   (13D)
   │                                      └─ Existing generation engine
   │                                              └─ Providers (Veo, images, TTS, …)
   │
   └─ Bot ── updates ──► Bot worker ──► same ProductService
                              │
                              └─ Notification outbox drain
```

The bot is not the generator. Handlers call `ProductService` only.

## Authentication

Mini App `initData` is validated server-side (HMAC-SHA256, Telegram WebApp
algorithm). The backend upserts `TelegramUser` by `telegram_user_id`.
Username is display-only.

## Async generation

`POST /generate` returns a job id. Status is polled from the Mini App.
The user may close the WebApp. Workers update `GenerationJob` and append
`NotificationOutbox` rows. A bot worker sends “video is ready” with an
Open Project button.

## Storage

Canonical masters live in `StorageBackend` (local now, S3/R2 later).
Telegram is a delivery channel, not the archive.

## Phase boundaries

| Phase | Build |
|---|---|
| 13A | Domain, services, docs, mock demo (this) |
| 13B | HTTP API over ProductService |
| 13C | PostgreSQL |
| 13D | Queue/workers calling the existing engine |
| 13C/13D | PostgreSQL + durable mock workers (current) |
| 13E | Bot |
| 13F | Stars invoices |
| 14x | Mini App UI |
