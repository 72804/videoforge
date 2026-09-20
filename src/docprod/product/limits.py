from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ProductLimits(BaseModel):
    """Central product caps. Do not scatter business limits in handlers."""

    model_config = ConfigDict(extra="forbid")

    max_projects_per_user: int = 50
    max_characters_per_project: int = 12
    max_scenes_per_project: int = 40
    max_duration_seconds: float = 180.0
    max_upload_bytes: int = 8 * 1024 * 1024
    max_concurrent_jobs_per_user: int = 2
    max_concurrent_jobs_per_project: int = 1
    max_generations_per_hour: int = 8
    max_provider_usd_per_job: float = 8.0
    quote_ttl_seconds: int = 15 * 60
    init_data_max_age_seconds: int = 24 * 60 * 60
    default_billing_mechanism: str = "PAY_PER_GENERATION"


DEFAULT_LIMITS = ProductLimits()
