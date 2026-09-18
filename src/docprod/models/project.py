from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from docprod.storage.paths import validate_project_id

SCHEMA_VERSION = "1.0"


class Project(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    id: str
    title: str
    language: str
    target_duration_seconds: float
    created_at: datetime
    updated_at: datetime
    random_seed: int = 42
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def _id_must_be_safe(cls, value: str) -> str:
        return validate_project_id(value)

    @field_validator("title")
    @classmethod
    def _title_not_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("title must not be empty")
        return value

    @field_validator("language")
    @classmethod
    def _language_not_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("language must not be empty")
        return value

    @field_validator("target_duration_seconds")
    @classmethod
    def _duration_positive(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("target_duration_seconds must be > 0")
        return value

    @field_validator("created_at", "updated_at")
    @classmethod
    def _timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("datetimes must be timezone-aware UTC")
        return value.astimezone(UTC)
