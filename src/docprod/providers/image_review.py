from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from docprod.storage.json_store import load_model, save_model
from docprod.storage.paths import ProjectPaths

ReviewState = Literal["generated", "approved", "rejected", "superseded"]


class ImageReviewRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    scene_id: str
    review_state: ReviewState
    artifact_sha256: str | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    note: str | None = None


def load_review(paths: ProjectPaths, scene_id: str) -> ImageReviewRecord | None:
    path = paths.scene_image_review(scene_id)
    if not path.is_file():
        return None
    try:
        return load_model(path, ImageReviewRecord)
    except (OSError, ValueError):
        return None


def save_review(paths: ProjectPaths, record: ImageReviewRecord) -> None:
    save_model(paths.scene_image_review(record.scene_id), record)


def set_review_state(
    paths: ProjectPaths,
    scene_id: str,
    review_state: ReviewState,
    *,
    artifact_sha256: str | None = None,
    note: str | None = None,
) -> ImageReviewRecord:
    existing = load_review(paths, scene_id)
    record = ImageReviewRecord(
        scene_id=scene_id,
        review_state=review_state,
        artifact_sha256=artifact_sha256 or (existing.artifact_sha256 if existing else None),
        note=note,
    )
    save_review(paths, record)
    return record
