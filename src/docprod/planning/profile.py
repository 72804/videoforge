from __future__ import annotations

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


class ScenePlannerProfile(BaseModel):
    """Planner policy. Beat duration bounds are not Scene schema rules."""

    model_config = ConfigDict(extra="forbid")

    name: str = "documentary_v1"
    planner_version: str = "1.0"
    min_scene_duration: float = 2.0
    target_scene_duration: float = 3.5
    max_scene_duration: float = 6.0
    max_ai_video_fraction: float = 0.15
    max_consecutive_ai_video: int = 1
    max_consecutive_same_effect: int = 2
    max_consecutive_same_strategy: int = 2
    prefer_cut_transition: bool = True
    short_gap_threshold: float = 0.5

    @field_validator("name", "planner_version")
    @classmethod
    def _not_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value

    @model_validator(mode="after")
    def _ranges(self) -> ScenePlannerProfile:
        if not 0 < self.min_scene_duration <= self.target_scene_duration <= self.max_scene_duration:
            raise ValueError(
                "require 0 < min_scene_duration <= target_scene_duration <= max_scene_duration"
            )
        if not 0 <= self.max_ai_video_fraction <= 1:
            raise ValueError("max_ai_video_fraction must be in [0, 1]")
        if self.max_consecutive_ai_video < 1:
            raise ValueError("max_consecutive_ai_video must be >= 1")
        if self.max_consecutive_same_effect < 1:
            raise ValueError("max_consecutive_same_effect must be >= 1")
        if self.max_consecutive_same_strategy < 1:
            raise ValueError("max_consecutive_same_strategy must be >= 1")
        if self.short_gap_threshold < 0:
            raise ValueError("short_gap_threshold must be >= 0")
        return self


DOCUMENTARY_V1 = ScenePlannerProfile()
STORY_DOCUMENTARY_V1 = ScenePlannerProfile(
    name="story_documentary_v1",
    planner_version="1.0",
    min_scene_duration=2.0,
    target_scene_duration=4.0,
    max_scene_duration=7.0,
    max_ai_video_fraction=0.10,
    max_consecutive_ai_video=2,
    max_consecutive_same_effect=2,
    max_consecutive_same_strategy=3,
)
PROFILES: dict[str, ScenePlannerProfile] = {
    DOCUMENTARY_V1.name: DOCUMENTARY_V1,
    STORY_DOCUMENTARY_V1.name: STORY_DOCUMENTARY_V1,
}


def get_profile(name: str) -> ScenePlannerProfile:
    try:
        return PROFILES[name]
    except KeyError as exc:
        known = ", ".join(sorted(PROFILES))
        raise ValueError(f"Unknown planner profile {name!r}. Known: {known}") from exc
