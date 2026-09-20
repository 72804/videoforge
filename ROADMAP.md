# Docprod roadmap

The generation engine in this repository remains. The first commercial
surface is a **Telegram Mini App + Telegram Bot** for editable AI video
projects. A standalone public HTTP API is postponed, not discarded.

Phase 8–12 remain historical engine work (research, semantic planning,
quality router, Birko/Maple canaries). They are not the product UI.

---

## CURRENT

### 13B Telegram backend API

FastAPI `/api/v1` over `ProductService`. Mock worker, HMAC sessions,
dev-only simulated payments. No paid providers. No PostgreSQL.

---

## NEXT

| Phase | Scope |
|---|---|
| 13B | Telegram backend API over `ProductService` |
| 13C | PostgreSQL + migrations |
| 13D | Async worker/queue calling the existing engine |
| 13E | Telegram bot (`/start`, Mini App button, notifications) |
| 13F | Telegram Stars payments (server-confirmed, idempotent) |
| 14A | Mini App shell |
| 14B | Create Video flow |
| 14C | Character manager |
| 14D | Generation/progress UI |
| 14E | Project viewer |
| 14F | Scene editor |
| 14G | Regeneration/version UI |
| 14H | Export/share |
| 15A | Production object storage (S3/R2) |
| 15B | Deployment/scaling |
| 15C | Analytics/admin |
| 16 | Public automation API (if still desired) |

---

## Explicitly not now

Full polished Mini App, Stripe, subscriptions, public developer API,
desktop Premiere-style timeline, social publishing, YouTube/TikTok
automation, new model adapters, Runway product work.

---

## Late-stage creator controls (engine)

Prompt-driven scene edit, per-scene regen, model pickers, and versioning
are now scheduled through **14B–14G** on Telegram, not as a generic SaaS
web app. Engine primitives already include quality profiles, custom
character refs, and paid-job journals.
