from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from docprod.models.enums import AssetStrategy
from docprod.models.scene import ScenePlan
from docprod.models.script import TIMING_TOLERANCE


class ContentCategory(StrEnum):
    location_establishing = "location_establishing"
    time_establishing = "time_establishing"
    person = "person"
    money = "money"
    police = "police"
    crime = "crime"
    vehicle = "vehicle"
    building = "building"
    document = "document"
    news = "news"
    map_or_travel = "map_or_travel"
    technology = "technology"
    phone_or_computer = "phone_or_computer"
    court_or_legal = "court_or_legal"
    nature = "nature"
    crowd = "crowd"
    interior = "interior"
    action = "action"
    danger = "danger"
    generic = "generic"


class ClassificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primary_category: ContentCategory
    matched_categories: list[ContentCategory] = Field(default_factory=list)
    matched_terms: list[str] = Field(default_factory=list)
    rule_score: int = 0
    motion_terms: list[str] = Field(default_factory=list)
    motion_score: int = 0


@dataclass
class VisualBeat:
    start: float
    end: float
    text: str
    source_utterance_ids: list[str]
    segmentation_reason: str
    visual_bridge: bool = False
    classification: ClassificationResult | None = None
    metadata: dict[str, object] = field(default_factory=dict)

    @property
    def duration(self) -> float:
        return self.end - self.start


class ScenePlanStats(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene_count: int
    total_duration: float
    coverage_duration: float
    average_scene_duration: float
    min_scene_duration: float
    max_scene_duration: float
    strategy_counts: dict[str, int]
    effect_counts: dict[str, int]
    transition_counts: dict[str, int]
    ai_video_duration: float
    ai_video_fraction: float
    ai_image_duration: float


def round_time(value: float) -> float:
    return round(value + 0.0, 4)


def times_touch(left_end: float, right_start: float) -> bool:
    return abs(right_start - left_end) <= TIMING_TOLERANCE


def summarize_scene_plan(plan: ScenePlan) -> ScenePlanStats:
    scenes = plan.scenes
    durations = [scene.duration for scene in scenes]
    coverage = sum(durations)
    strategy_counts: dict[str, int] = {}
    effect_counts: dict[str, int] = {}
    transition_counts: dict[str, int] = {}
    ai_video = 0.0
    ai_image = 0.0
    for scene in scenes:
        key = scene.asset_strategy.value
        strategy_counts[key] = strategy_counts.get(key, 0) + 1
        effect_counts[scene.effect.value] = effect_counts.get(scene.effect.value, 0) + 1
        trans_key = scene.transition.value
        transition_counts[trans_key] = transition_counts.get(trans_key, 0) + 1
        if scene.asset_strategy is AssetStrategy.ai_image_to_video:
            ai_video += scene.duration
        elif scene.asset_strategy is AssetStrategy.ai_image:
            ai_image += scene.duration
    avg = coverage / len(durations) if durations else 0.0
    return ScenePlanStats(
        scene_count=len(scenes),
        total_duration=plan.total_duration,
        coverage_duration=round_time(coverage),
        average_scene_duration=round_time(avg),
        min_scene_duration=round_time(min(durations) if durations else 0.0),
        max_scene_duration=round_time(max(durations) if durations else 0.0),
        strategy_counts=dict(sorted(strategy_counts.items())),
        effect_counts=dict(sorted(effect_counts.items())),
        transition_counts=dict(sorted(transition_counts.items())),
        ai_video_duration=round_time(ai_video),
        ai_video_fraction=round(ai_video / coverage, 6) if coverage else 0.0,
        ai_image_duration=round_time(ai_image),
    )
