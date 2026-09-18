from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from docprod.models.enums import JobStatus, StageStatus
from docprod.models.project import SCHEMA_VERSION


class StageRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    status: StageStatus = StageStatus.pending
    started_at: datetime | None = None
    finished_at: datetime | None = None
    input_hash: str | None = None
    output_hash: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("started_at", "finished_at")
    @classmethod
    def _timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("datetimes must be timezone-aware UTC")
        return value.astimezone(UTC)


class JobState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    project_id: str
    status: JobStatus = JobStatus.pending
    created_at: datetime
    updated_at: datetime
    current_stage: str | None = None
    stages: list[StageRecord] = Field(default_factory=list)

    @field_validator("created_at", "updated_at")
    @classmethod
    def _timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("datetimes must be timezone-aware UTC")
        return value.astimezone(UTC)
