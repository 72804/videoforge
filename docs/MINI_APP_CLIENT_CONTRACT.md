# Mini App client contract (Phase 13B)

Session tokens are HMAC-signed `{user_id}.{exp}.{sig}`. `telegram_user_id`
is never a credential. Header: `Authorization: Bearer <token>`.

## Happy path

1. Telegram opens the Mini App and supplies `initData`.
2. `POST /api/v1/auth/telegram` `{ "init_data": "..." }` → `{ token, user }`.
3. `POST /api/v1/projects` with prompt + AUTO/FIXED duration.
4. `POST /api/v1/projects/{id}/characters` then multipart
   `POST /api/v1/characters/{id}/references`.
5. `POST /api/v1/projects/{id}/plan` (server estimate, mock outline if empty).
6. `POST /api/v1/projects/{id}/quote` `{ plan_id }`.
7. Pay: production will use Telegram Stars (13F). Development only:
   `POST /api/v1/dev/payments/{quote_id}/confirm` when `APP_ENV` is
   `development` or `test`.
8. `POST /api/v1/projects/{id}/generate` `{ quote_id }` → **202** `{ job_id, status }`.
   Send `Idempotency-Key` for retries.
9. Poll `GET /api/v1/jobs/{job_id}` using `work_units` (completed/total), not %.
   Local mock: `POST /api/v1/dev/jobs/{job_id}/run`.
10. `GET /api/v1/projects/{id}/scenes` → tap `GET /api/v1/scenes/{id}`.
11. Edit `PATCH /api/v1/scenes/{id}` (new version + `invalidated`).
    Re-plan and re-quote after generation-relevant edits.
12. Regen image/video: plan kind `scene_image` / `scene_video`, quote, pay,
    `POST .../regenerate-image|video`.
13. `POST /api/v1/projects/{id}/render` after a render quote.
14. Preview via `GET /api/v1/media/{asset_version_id}` (dev, authz-checked).

## Errors

JSON `{ "error": { "code", "message", "details" } }`.

| Code | Client action |
|---|---|
| AUTH_INVALID / AUTH_EXPIRED | Re-run initData auth |
| FORBIDDEN / NOT_FOUND | Stop; do not retry other user's ids |
| QUOTE_EXPIRED / PLAN_STALE | Re-plan + quote |
| PAYMENT_REQUIRED | Confirm payment (dev or Stars) |
| JOB_CONFLICT | Poll existing job |
| SCENE_LOCKED | Unlock first |
| IDEMPOTENCY_CONFLICT | New idempotency key |
| LIMIT_EXCEEDED / INVALID_UPLOAD | Fix input |

Retries: only GET and idempotent POST with the **same** key and body.
Do not send client-computed Stars or `payment_success`.
