from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from docprod.stock import STOCK_LICENSE_NOTE


class StockVideoFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_id: int | None = None
    quality: str | None = None
    file_type: str | None = None
    width: int
    height: int
    link: str
    fps: float | None = None


class StockVideoCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    provider_video_id: str
    source_page_url: str
    creator_name: str
    creator_url: str | None = None
    duration: float
    width: int
    height: int
    fps: float | None = None
    preview_image_url: str | None = None
    query: str
    video_files: list[StockVideoFile] = Field(default_factory=list)
    score: float = 0.0
    score_reasons: list[str] = Field(default_factory=list)
    rejected: bool = False
    reject_reason: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class StockSearchPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str
    videos: list[StockVideoCandidate]
    ratelimit_limit: str | None = None
    ratelimit_remaining: str | None = None
    ratelimit_reset: str | None = None


class StockSourceManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    scene_id: str
    provider: str
    provider_video_id: str
    source_page_url: str
    creator_name: str
    creator_url: str | None = None
    duration: float
    width: int
    height: int
    fps: float | None = None
    download_url: str
    downloaded_path: str
    sha256: str
    query: str
    license_note: str = STOCK_LICENSE_NOTE
    selected_rendition: dict[str, Any] = Field(default_factory=dict)
    clip_start: float | None = None
    clip_duration: float | None = None
    clip_path: str | None = None
    clip_sha256: str | None = None
    effect_override_reason: str | None = "native_video_motion"
    retrieved_at: str | None = None


class StockCreditRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene_id: str
    provider: str
    creator: str
    source_url: str
    provider_video_id: str


class StockCreditsManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    project_id: str
    sources: list[StockCreditRecord] = Field(default_factory=list)


class SceneStockSearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene_id: str
    narration: str
    queries: list[str]
    candidates: list[StockVideoCandidate]
    contact_sheet: str | None = None


class StockSearchManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    project_id: str
    provider: str = "pexels"
    search_url: str
    scenes: list[SceneStockSearchResult] = Field(default_factory=list)
    ratelimit_limit: str | None = None
    ratelimit_remaining: str | None = None
    ratelimit_reset: str | None = None
    retrieved_at: str | None = None
