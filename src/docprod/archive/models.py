from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ArchiveReuseDecision = Literal["AUTO_REUSABLE", "REVIEW_REQUIRED", "REJECT"]


class ArchiveCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = "wikimedia_commons"
    page_id: int | None = None
    title: str
    description_url: str = ""
    file_url: str = ""
    thumb_url: str = ""
    mime: str = ""
    media_type: str = ""
    width: int = 0
    height: int = 0
    size_bytes: int = 0
    artist: str = ""
    credit: str = ""
    description: str = ""
    date_original: str = ""
    license_short_name: str = ""
    license_url: str = ""
    usage_terms: str = ""
    copyrighted: str = ""
    attribution: str = ""
    attribution_required: bool = True
    non_free: bool = False
    restrictions: str = ""
    decision: ArchiveReuseDecision = "REVIEW_REQUIRED"
    decision_reason: str = ""
    score: float = 0.0
    score_reasons: list[str] = Field(default_factory=list)
    raw_extmetadata: dict[str, Any] = Field(default_factory=dict)
    query: str = ""


class ArchiveSourceManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    asset_unit_id: str
    provider: str = "wikimedia_commons"
    title: str
    description_url: str
    file_url: str
    artist: str = ""
    credit: str = ""
    license_short_name: str
    license_url: str = ""
    usage_terms: str = ""
    attribution_text: str = ""
    attribution_required: bool = True
    restrictions: str = ""
    retrieved_at: str
    sha256: str
    local_path: str
    width: int = 0
    height: int = 0


class ArchiveCreditsManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    project_id: str
    sources: list[ArchiveSourceManifest] = Field(default_factory=list)
