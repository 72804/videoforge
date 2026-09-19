from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from docprod.research.models import ApiUsage

SEMANTIC_PLANNER_PROMPT_VERSION = "1.0"
STORY_WORDS_PER_MINUTE = 145.0

PreferredSourceType = Literal[
    "archive",
    "stock_video",
    "ai_reenactment",
    "document",
    "newspaper",
    "map",
    "infographic",
    "text_card",
    "photograph",
    "mixed",
    "none",
]
MovementNeed = Literal["none", "low", "medium", "high"]
HistoricalSpecificity = Literal[
    "generic",
    "approximate_period",
    "exact_place_or_object",
    "exact_person_or_event",
]
ReenactmentFreedom = Literal["generic_only", "constrained", "avoid"]
ReenactmentType = Literal["generic", "illustrative", "historically_constrained"]


class SemanticSceneIntent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    intent_id: str
    chapter: str = ""
    narration_span: str = ""
    narration_start_word: int = 0
    narration_end_word: int = 0
    visual_subject: str = ""
    visual_action: str = ""
    visual_environment: str = ""
    visual_purpose: str = ""
    preferred_source_type: PreferredSourceType = "stock_video"
    movement_need: MovementNeed = "low"
    historical_specificity: HistoricalSpecificity = "generic"
    continuity_entities: list[str] = Field(default_factory=list)
    claim_ids: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    reenactment_freedom: ReenactmentFreedom = "generic_only"
    reenactment_type: ReenactmentType | None = None
    reasoning_summary: str = ""
    visual_description: str = ""
    image_prompt_seed: str = ""
    stock_query_seed: str = ""
    archive_search_seed: str = ""
    graphic_brief: str = ""
    explicit_explainer: bool = False


class SemanticIntentSet(BaseModel):
    model_config = ConfigDict(extra="ignore")

    schema_version: str = "1.0"
    project_id: str
    model: str = ""
    request_hash: str = ""
    prompt_version: str = SEMANTIC_PLANNER_PROMPT_VERSION
    intents: list[SemanticSceneIntent] = Field(default_factory=list)
    usage: ApiUsage | None = None
    cache_hit: bool = False


class PlanWarning(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    scene_id: str = ""
    message: str


class StoryPlanDiagnostics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene_count: int = 0
    estimated_runtime_seconds: float = 0.0
    average_scene_duration: float = 0.0
    min_scene_duration: float = 0.0
    max_scene_duration: float = 0.0
    strategy_counts: dict[str, int] = Field(default_factory=dict)
    ai_video_seconds: float = 0.0
    ai_video_fraction: float = 0.0
    archive_opportunities: int = 0
    stock_scenes: int = 0
    ai_still_scenes: int = 0
    ai_video_scenes: int = 0
    map_scenes: int = 0
    document_scenes: int = 0
    graphic_scenes: int = 0
    reenactment_count: int = 0
    named_person_archive_opportunities: int = 0
    claims_referenced: int = 0
    sources_referenced: int = 0
    repetition_warnings: list[PlanWarning] = Field(default_factory=list)
    hallucination_warnings: list[PlanWarning] = Field(default_factory=list)
    diversity_warnings: list[PlanWarning] = Field(default_factory=list)
