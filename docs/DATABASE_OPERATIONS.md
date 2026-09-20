# Database operations

Product data lives in PostgreSQL when `PRODUCT_PERSISTENCE=postgres`.
Engine projects (Birko, Maple, Veo cache) stay on the filesystem.

## Configuration

```bash
export PRODUCT_PERSISTENCE=postgres
export DATABASE_URL=postgresql+psycopg://docprod:docprod@127.0.0.1:5432/docprod
```

Do not commit credentials. Tests use `TEST_DATABASE_URL` when set; they never
require a developer’s production database.

## Migrations

The application does **not** call `create_all` at runtime.

```bash
uv run alembic upgrade head
uv run alembic downgrade -1
```

Initial revision: `alembic/versions/20260920_0001_initial_product.py`.

## Persistence modes

| `PRODUCT_PERSISTENCE` | Store |
|---|---|
| `json` (default) | `product_data/store.json` plus local blobs |
| `postgres` | PostgreSQL + `StorageBackend` for bytes |

JSON mode remains for fast unit tests and lightweight local work.

## Import (optional)

`product_data/store.json` is development/test data, not Birko/Maple assets.

```bash
PRODUCT_PERSISTENCE=postgres uv run docprod telegram-product-import-json --store product_data/store.json
```

Skip this if the JSON file is only leftover HTTP fixtures.
