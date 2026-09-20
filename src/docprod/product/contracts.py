from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ProjectSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    thumbnail: str | None = None
    duration: float | None = None
    status: str
    progress: dict[str, int] | None = None
    updated_at: str


class SceneSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    order: int
    thumbnail_url: str | None = None
    duration: float
    characters: list[str]
    status: str
    production_type: str
    image_model: str
    video_model: str
    can_regenerate: bool
    estimated_regeneration_stars: int


class JobStatusView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    status: str
    units: list[dict[str, int | str | bool]]
    authorized: bool
