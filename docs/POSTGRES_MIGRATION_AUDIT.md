# PostgreSQL migration audit (Phase 13C)

Inventory of persistence that was process-local before this phase.
Engine artifacts (Birko, Maple, Veo cache) are **not** in scope.

## In-memory dictionaries

| Location | What |
|---|---|
| `src/docprod/product/repository.py` `MemoryRepository` | Canonical store: users, projects, characters, references, scripts, scenes, versions, assets, plans, quotes, jobs, attempts, renders, transactions, payments, outbox, idempotency |
| Secondary indexes | `users_by_telegram`, `txn_by_idempotency`, `payments_by_telegram` |

`ProductService` mutates these dicts in place (`job.status = …`, `quote.status = …`).

## JSON persistence

| Location | What |
|---|---|
| `src/docprod/product/persist.py` | Dump/load every table to JSON |
| `src/docprod/api/app.py` persist middleware | Writes `product_data/store.json` after **every** HTTP request |
| `telegram-api-seed` | Seeds JSON store |
| `Settings.product_store_path` | Path config |

JSON is a full-document snapshot. It cannot implement `SELECT … FOR UPDATE SKIP LOCKED`, payment uniqueness under concurrency, or API/worker process split.

## Process-local locks / idempotency / jobs / payments

| Location | Risk |
|---|---|
| `src/docprod/api/idempotency.py` | Records live in `repo.idempotency` (JSON after request). Races across processes. |
| `MemoryRepository.put_payment` | First-writer in **this** process only |
| `MemoryRepository.put_transaction` | Idempotency map is process-local |
| `ProductService._assert_job_slot` / concurrent job counts | Scan in-memory `jobs` |
| `MockGenerationWorker` via `POST /api/v1/dev/jobs/{id}/run` | Inline in the API process |
| Job model | No `claimed_by` / lease / heartbeat |
| Attempts | No `remote_operation_id` / recovery status |

## API contract to preserve

- `/api/v1/*` JSON shapes
- Simulated `POST /api/v1/dev/payments/{quote_id}/confirm`
- `POST …/generate` → 202
- `GET /api/v1/jobs/{id}` work units
- Ownership 403 across users
- Dev job run endpoint remains for JSON/unit tests

## Migration decision

| Concern | Choice |
|---|---|
| Stack | SQLAlchemy 2.x + Alembic + psycopg3 (sync). FastAPI routes are already sync. |
| Dual backend | `PRODUCT_PERSISTENCE=json` (default tests/light) or `postgres` |
| Domain vs ORM | Pydantic domain models unchanged in role; `docprod.db.orm` is persistence-only |
| Queue | `generation_jobs` + `FOR UPDATE SKIP LOCKED` |
| JSON store | Kept. Not deleted. Optional import CLI for `product_data/store.json` |
| Birko / Maple | Stay on filesystem; not imported into product DB |
