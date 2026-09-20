# Telegram database design (not deployed)

PostgreSQL target schema for Phase 13C. 13A uses an in-memory repository
with the same uniqueness rules.

```sql
CREATE TABLE telegram_users (
  id UUID PRIMARY KEY,
  telegram_user_id BIGINT NOT NULL UNIQUE,
  username TEXT,
  first_name TEXT,
  language_code TEXT,
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE projects (
  id UUID PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES telegram_users(id),
  title TEXT NOT NULL,
  prompt TEXT NOT NULL,
  content_type TEXT NOT NULL,
  status TEXT NOT NULL,
  duration_mode TEXT NOT NULL,
  target_duration_seconds DOUBLE PRECISION,
  aspect_ratio TEXT NOT NULL,
  language TEXT NOT NULL,
  quality_profile TEXT NOT NULL,
  default_image_model TEXT NOT NULL,
  default_video_model TEXT NOT NULL,
  default_text_model TEXT NOT NULL,
  default_voice_model TEXT NOT NULL,
  active_script_version_id UUID,
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX projects_user_id_idx ON projects(user_id);

CREATE TABLE characters (
  id UUID PRIMARY KEY,
  project_id UUID NOT NULL REFERENCES projects(id),
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  locked_identity BOOLEAN NOT NULL DEFAULT FALSE,
  primary_reference_id UUID,
  created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX characters_project_id_idx ON characters(project_id);

CREATE TABLE character_references (
  id UUID PRIMARY KEY,
  character_id UUID NOT NULL REFERENCES characters(id),
  project_id UUID NOT NULL REFERENCES projects(id),
  storage_key TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  mode TEXT NOT NULL,
  primary_flag BOOLEAN NOT NULL,
  created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE script_versions (
  id UUID PRIMARY KEY,
  project_id UUID NOT NULL REFERENCES projects(id),
  body TEXT NOT NULL,
  language TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE scenes (
  id UUID PRIMARY KEY,
  project_id UUID NOT NULL REFERENCES projects(id),
  order_index INTEGER NOT NULL,
  active_version_id UUID,
  locked BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL,
  UNIQUE (project_id, order_index)
);

CREATE TABLE scene_versions (
  id UUID PRIMARY KEY,
  scene_id UUID NOT NULL REFERENCES scenes(id),
  project_id UUID NOT NULL REFERENCES projects(id),
  visual_prompt TEXT NOT NULL,
  motion_prompt TEXT NOT NULL DEFAULT '',
  character_ids UUID[] NOT NULL DEFAULT '{}',
  dialogue TEXT NOT NULL DEFAULT '',
  narration TEXT NOT NULL DEFAULT '',
  duration_seconds DOUBLE PRECISION NOT NULL,
  production_class TEXT NOT NULL,
  image_model TEXT NOT NULL,
  video_model TEXT NOT NULL,
  image_asset_version_id UUID,
  video_asset_version_id UUID,
  image_stale BOOLEAN NOT NULL,
  video_stale BOOLEAN NOT NULL,
  created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE assets (
  id UUID PRIMARY KEY,
  project_id UUID NOT NULL REFERENCES projects(id),
  scene_id UUID,
  kind TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE asset_versions (
  id UUID PRIMARY KEY,
  asset_id UUID NOT NULL REFERENCES assets(id),
  storage_key TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  model TEXT NOT NULL DEFAULT '',
  provider TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE generation_plans (
  id UUID PRIMARY KEY,
  project_id UUID NOT NULL REFERENCES projects(id),
  plan_hash TEXT NOT NULL,
  estimated_provider_usd NUMERIC NOT NULL,
  customer_stars INTEGER NOT NULL,
  items JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE star_quotes (
  id UUID PRIMARY KEY,
  project_id UUID NOT NULL REFERENCES projects(id),
  user_id UUID NOT NULL REFERENCES telegram_users(id),
  generation_plan_id UUID NOT NULL REFERENCES generation_plans(id),
  generation_plan_hash TEXT NOT NULL,
  quote_hash TEXT NOT NULL,
  stars INTEGER NOT NULL,
  estimated_provider_usd NUMERIC NOT NULL,
  created_at TIMESTAMPTZ NOT NULL,
  expires_at TIMESTAMPTZ NOT NULL,
  status TEXT NOT NULL
);

CREATE TABLE generation_jobs (
  id UUID PRIMARY KEY,
  project_id UUID NOT NULL REFERENCES projects(id),
  user_id UUID NOT NULL REFERENCES telegram_users(id),
  quote_id UUID,
  plan_hash TEXT NOT NULL,
  status TEXT NOT NULL,
  authorized BOOLEAN NOT NULL,
  payment_id UUID,
  progress JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX generation_jobs_user_status_idx ON generation_jobs(user_id, status);

CREATE TABLE generation_attempts (
  id UUID PRIMARY KEY,
  job_id UUID NOT NULL REFERENCES generation_jobs(id),
  scene_id UUID,
  item_type TEXT NOT NULL,
  provider TEXT NOT NULL,
  model TEXT NOT NULL,
  provider_outcome TEXT NOT NULL,
  provider_billed TEXT NOT NULL,
  customer_billing TEXT NOT NULL,
  error_code TEXT,
  created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE renders (
  id UUID PRIMARY KEY,
  project_id UUID NOT NULL REFERENCES projects(id),
  storage_key TEXT NOT NULL,
  stale BOOLEAN NOT NULL,
  created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE star_transactions (
  id UUID PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES telegram_users(id),
  project_id UUID,
  generation_job_id UUID,
  type TEXT NOT NULL,
  telegram_payment_id TEXT,
  stars INTEGER NOT NULL,
  idempotency_key TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE telegram_payments (
  id UUID PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES telegram_users(id),
  quote_id UUID NOT NULL REFERENCES star_quotes(id),
  telegram_payment_id TEXT NOT NULL UNIQUE,
  stars INTEGER NOT NULL,
  status TEXT NOT NULL,
  invoice_payload TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE notification_outbox (
  id UUID PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES telegram_users(id),
  project_id UUID,
  job_id UUID,
  kind TEXT NOT NULL,
  payload JSONB NOT NULL,
  status TEXT NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX notification_outbox_status_idx ON notification_outbox(status, created_at);
```

Idempotency: `star_transactions.idempotency_key` unique;
`telegram_payments.telegram_payment_id` unique.
