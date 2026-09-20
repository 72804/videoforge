from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from docprod.quality.enums import (
    AdapterStatus,
    CostConfidence,
    Modality,
    PriceMode,
    ProviderStatus,
    QualityProfile,
    QualityTier,
    SceneProductionClass,
    SfxClass,
    UpgradeKind,
)


class PricingSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: PriceMode = PriceMode.UNKNOWN
    value: float | None = None
    unit: str = ""
    notes: str = ""
    confidence: CostConfidence = CostConfidence.UNRESOLVED
    pricing_as_of: str = ""
    source_note: str = ""


class CapabilitySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    names: tuple[str, ...] = ()


class ModelSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_id: str
    provider: str
    modality: Modality
    display_name: str = ""
    capabilities: tuple[str, ...] = ()
    quality_tier: QualityTier = QualityTier.STANDARD
    speed_tier: str = "unknown"
    pricing: PricingSpec = Field(default_factory=PricingSpec)
    implemented: bool = False
    adapter_status: AdapterStatus = AdapterStatus.CATALOG_ONLY
    async_remote: bool = False
    local: bool = False
    notes: str = ""
    duration_options: tuple[int, ...] = ()
    min_duration_seconds: float | None = None
    max_duration_seconds: float | None = None


class ProviderSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_id: str
    display_name: str
    env_key: str = ""
    local_url_attr: str = ""
    status: ProviderStatus = ProviderStatus.UNCONFIGURED
    models: tuple[str, ...] = ()


class SceneValueScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    story_importance: float = 0.4
    motion_need: float = 0.2
    character_importance: float = 0.3
    dialogue_importance: float = 0.0
    performance_precision: float = 0.0
    visual_novelty: float = 0.4
    emotional_intensity: float = 0.3
    camera_complexity: float = 0.2

    def clamp(self) -> SceneValueScore:
        fields = {
            name: max(0.0, min(1.0, float(getattr(self, name))))
            for name in type(self).model_fields
        }
        return self.model_copy(update=fields)


class CostLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str
    provider: str
    model_id: str
    count: float = 0.0
    quantity: float = 0.0
    unit: str = ""
    unit_price: float | None = None
    estimated_cost: float | None = None
    confidence: CostConfidence = CostConfidence.UNRESOLVED
    notes: str = ""


class RouteDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene_id: str
    production_class: SceneProductionClass
    quality_profile: QualityProfile
    selected_provider: str
    selected_model: str
    fallback_chain: list[str] = Field(default_factory=list)
    estimated_cost: float | None = None
    cost_confidence: CostConfidence = CostConfidence.UNRESOLVED
    reason: str = ""
    quality_tier: QualityTier = QualityTier.STANDARD
    scores: SceneValueScore = Field(default_factory=SceneValueScore)
    must_video: bool = False
    must_static: bool = False
    must_performance: bool = False
    locked_provider: str = ""
    sfx_class: SfxClass | None = None
    music_sync_required: bool = False
    used_seconds: float = 0.0
    billable_seconds: float = 0.0
    wasted_seconds: float = 0.0
    effective_cost_per_used_second: float | None = None
    upgrade_kind: UpgradeKind = UpgradeKind.STILL_LOCAL_MOTION
    needs_driving_performance: bool = False


class CharacterProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    character_id: str
    name: str
    description: str = ""
    canonical_refs: list[str] = Field(default_factory=list)
    appearance_notes: str = ""
    generation_hashes: list[str] = Field(default_factory=list)


class CharacterReferenceSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    profiles: list[CharacterProfile] = Field(default_factory=list)


class DialogueShotRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene_id: str
    character_refs: list[str] = Field(default_factory=list)
    source_image: str = ""
    source_video: str = ""
    audio: str = ""
    dialogue_text: str
    duration: float
    emotion: str = ""
    camera_instructions: str = ""


class PerformanceShotRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene_id: str
    driving_video: str = ""
    character_refs: list[str] = Field(default_factory=list)
    location_refs: list[str] = Field(default_factory=list)
    target_audio: str = ""
    shot_duration: float
    camera_preservation: bool = True
    motion_preservation: bool = True


class DrivingPerformanceAsset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: str
    source_kind: str
    path: str = ""
    notes: str = ""
    celebrity_likeness: bool = False


class EpisodeCostPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    profile: QualityProfile
    lines: list[CostLine] = Field(default_factory=list)
    canonical_target_value: float | None = None
    cached_value: float = 0.0
    remaining_spend: float | None = None
    hard_budget: float
    budget_remaining: float
    known_cost: float = 0.0
    estimated_cost: float = 0.0
    unresolved_categories: list[str] = Field(default_factory=list)
    unresolved_cost_items: list[str] = Field(default_factory=list)
    estimated_lower_bound_usd: float = 0.0
    estimated_upper_bound_usd: float | None = None
    fully_priced: bool = True
    notes: list[str] = Field(default_factory=list)


class DrivingPerformancePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene_id: str
    duration: float
    dialogue_audio_target: str = ""
    required_motions: list[str] = Field(default_factory=list)
    camera_behavior: str = "locked medium shot"
    number_of_performers: int = 1
    recording_instructions: str = ""
    reference_character_bindings: list[str] = Field(default_factory=list)
    needs_driving_performance: bool = True


class TtsComparisonRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_id: str
    provider: str
    available: bool
    estimated_cost: float | None = None
    cost_confidence: CostConfidence = CostConfidence.UNRESOLVED
    profile_usage: str = ""
    tags: list[str] = Field(default_factory=list)
    downstream: list[str] = Field(default_factory=list)
