from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ShotAbRecord(BaseModel):
    """Offline human review of the SAME shot spec across providers. No generation here."""

    model_config = ConfigDict(extra="forbid")

    shot_spec_id: str
    model_id: str
    identity_consistency: int | None = None
    motion_quality: int | None = None
    prompt_adherence: int | None = None
    face_quality: int | None = None
    camera_quality: int | None = None
    dialogue_suitability: int | None = None
    artifact_level: int | None = None
    overall_preference: int | None = None
    notes: str = ""


class ShotAbBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shot_spec_id: str
    candidate_models: list[str] = Field(default_factory=list)
    records: list[ShotAbRecord] = Field(default_factory=list)
    executed: bool = False


DEFAULT_AB_CANDIDATES: tuple[str, ...] = (
    "veo-3.1-lite-generate-preview",
    "runway-gen-4.5",
    "seedance-2.5-image-to-video",
    "kling-3.0-pro-image-to-video",
)


def planned_ab_batch(shot_spec_id: str, models: list[str] | None = None) -> ShotAbBatch:
    ids = list(models or DEFAULT_AB_CANDIDATES)
    return ShotAbBatch(
        shot_spec_id=shot_spec_id,
        candidate_models=ids,
        records=[ShotAbRecord(shot_spec_id=shot_spec_id, model_id=mid) for mid in ids],
        executed=False,
    )
