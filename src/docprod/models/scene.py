from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from docprod.models.enums import AssetStrategy, Mood, TransitionType, VisualEffect
from docprod.models.project import SCHEMA_VERSION
from docprod.models.script import TIMING_TOLERANCE

SCENE_ID_PATTERN = re.compile(r"^scene_\d+$")


class GenerationSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    image_prompt: str | None = None
    negative_prompt: str | None = None
    motion_prompt: str | None = None
    seed: int | None = None


class SourceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    uri: str | None = None
    local_path: str | None = None
    title: str | None = None
    attribution: str | None = None
    license: str | None = None


class Scene(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    id: str
    start: float
    end: float
    duration: float
    narration: str
    visual_intent: str
    asset_strategy: AssetStrategy
    effect: VisualEffect
    transition: TransitionType
    mood: Mood
    subtitle: str
    generation: GenerationSpec = Field(default_factory=GenerationSpec)
    sources: list[SourceReference] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def _scene_id_format(cls, value: str) -> str:
        if not SCENE_ID_PATTERN.fullmatch(value):
            raise ValueError("scene id must match scene_<digits>, e.g. scene_0047")
        return value

    @field_validator("visual_intent")
    @classmethod
    def _visual_intent_not_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("visual_intent must not be empty")
        return value

    @model_validator(mode="after")
    def _validate_timing_and_generation(self) -> Scene:
        is_bridge = bool(self.metadata.get("visual_bridge"))
        if not self.narration.strip() and not is_bridge:
            raise ValueError("narration must not be empty")
        if self.start < 0:
            raise ValueError("scene start must be >= 0")
        if self.end <= self.start:
            raise ValueError("scene end must be > start")
        expected = self.end - self.start
        if abs(self.duration - expected) > TIMING_TOLERANCE:
            raise ValueError(
                f"duration {self.duration} must equal end - start ({expected}) "
                f"within {TIMING_TOLERANCE}"
            )
        if self.asset_strategy in {AssetStrategy.ai_image, AssetStrategy.ai_image_to_video}:
            if not (self.generation.image_prompt and self.generation.image_prompt.strip()):
                raise ValueError("generation.image_prompt is required for AI image strategies")
        return self


class ScenePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    project_id: str
    scenes: list[Scene] = Field(default_factory=list)
    total_duration: float

    @model_validator(mode="after")
    def _validate_plan(self) -> ScenePlan:
        seen: set[str] = set()
        previous: Scene | None = None
        for scene in self.scenes:
            if scene.id in seen:
                raise ValueError(f"duplicate scene id: {scene.id}")
            seen.add(scene.id)
            if previous is not None:
                if scene.start < previous.start:
                    raise ValueError("scenes must be ordered chronologically")
                if scene.start < previous.end - TIMING_TOLERANCE:
                    raise ValueError(
                        f"scenes {previous.id} and {scene.id} overlap "
                        f"({previous.end} vs {scene.start})"
                    )
            previous = scene
        expected_total = self.scenes[-1].end if self.scenes else 0.0
        if abs(self.total_duration - expected_total) > TIMING_TOLERANCE:
            raise ValueError(
                f"total_duration {self.total_duration} must equal final scene end "
                f"({expected_total}) within {TIMING_TOLERANCE}"
            )
        return self
