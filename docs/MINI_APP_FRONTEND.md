# Mini App frontend (Phase 14)

Next.js + TypeScript + React in `apps/telegram-mini-app/`. Independently
deployable from the Python API.

## Architecture

- Telegram WebApp `initData` → `POST /api/v1/auth/telegram` → HMAC session
- Dev browser: `POST /api/v1/dev/auth` (disabled in production)
- Typed client: `src/lib/api.ts` (Bearer, `X-Request-ID`, error mapping)
- Backend is source of truth. Job progress is always polled.

## Screens

| Route | Screen |
|---|---|
| `/` | Home |
| `/create` | Prompt |
| `/create/[id]/characters` | Characters |
| `/create/[id]/settings` | Video settings |
| `/create/[id]/review` | Review + simulated quote |
| `/jobs/[jobId]` | Generation progress |
| `/projects` | Project list |
| `/projects/[id]` | Project + scene strip |
| `/projects/[id]/scenes/[sceneId]` | Scene editor |
| `/credits` | Simulated Stars usage |
| `/settings` | Defaults |

## Telegram

`telegram-web-app.js` is loaded in the root layout. Theme colors map to CSS
variables. BackButton is used on settings and scene editor. Haptics fire on
save / generate when the SDK is present.

## Development

```bash
uv run docprod telegram-api-serve
cd apps/telegram-mini-app
npm install
npm run dev
```

Open http://127.0.0.1:3000 and use **Dev login**.

`NEXT_PUBLIC_APP_ENV=development` shows the simulated-payment banner and may
call `POST /api/v1/dev/jobs/{id}/run`. Production builds must set
`NEXT_PUBLIC_APP_ENV=production` so those controls are compiled out of the UI.

Frontend types live in `src/lib/types.ts`, aligned to `docs/openapi.json`.
They are an explicit layer (not codegen) so the Mini App stays lightweight.
