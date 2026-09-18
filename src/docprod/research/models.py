from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

RESEARCH_PROMPT_VERSION = "1.0"
DOSSIER_PROMPT_VERSION = "1.0"
MAX_WEB_TOOL_CALLS = 8

QualityTier = Literal["A", "B", "C", "low"]
FactConfidence = Literal["high", "medium", "low"]
FactStatus = Literal["confirmed", "attributed", "disputed", "uncertain"]


class TopicSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    project_id: str
    topic: str
    language: str = "tr"
    target_runtime_minutes: float
    target_audience: str = "general adult documentary viewers"
    content_type: str
    research_notes_optional: str = ""


class ApiUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_tokens: int | None = None
    reasoning_tokens: int | None = None
    web_search_call_count: int = 0
    duration_seconds: float = 0.0
    request_count: int = 1
    extra: dict[str, int | float | str] = Field(default_factory=dict)


class SourceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    url: str
    title: str = ""
    domain: str
    publisher: str | None = None
    publication_date: str | None = None
    accessed_at: datetime
    quality_tier: QualityTier
    quality_reason: str
    source_type: str = "web"
    used_by_research: bool = True
    notes: str = ""
    canonical_url: str = ""


class SourceRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    project_id: str
    sources: list[SourceRecord] = Field(default_factory=list)
    evidence_source_ids: list[str] = Field(default_factory=list)

    def discovered_count(self) -> int:
        return len(self.sources)

    def evidence_records(self) -> list[SourceRecord]:
        ids = set(self.evidence_source_ids)
        if not ids:
            return []
        return [item for item in self.sources if item.source_id in ids]


class ResearchRawResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    project_id: str
    response_id: str | None = None
    model: str
    request_hash: str
    prompt_version: str = RESEARCH_PROMPT_VERSION
    usage: ApiUsage | None = None
    web_search_calls: list[dict[str, Any]] = Field(default_factory=list)
    sources: list[dict[str, Any]] = Field(default_factory=list)
    output_text: str = ""
    citation_annotations: list[dict[str, Any]] = Field(default_factory=list)
    sanitized_response: dict[str, Any] = Field(default_factory=dict)
    cache_hit: bool = False
    generation_status: str = "success"


class QualityGateResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    passed: bool
    useful_source_count: int
    independent_domains: int
    tier_counts: dict[str, int] = Field(default_factory=dict)
    has_tier_a_or_strong_b: bool
    chronology_supported: bool
    value_claims_sourced: bool
    legal_outcomes_sourced: bool
    dangling_citations: list[str] = Field(default_factory=list)
    failures: list[str] = Field(default_factory=list)


class NamedRef(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    role: str = ""
    notes: str = ""
    source_ids: list[str] = Field(default_factory=list)


class LocationRef(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    notes: str = ""
    source_ids: list[str] = Field(default_factory=list)


class TimelineEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    event_id: str
    date_or_range: str
    description: str
    source_ids: list[str] = Field(default_factory=list)


class Fact(BaseModel):
    model_config = ConfigDict(extra="ignore")

    fact_id: str
    claim: str
    source_ids: list[str] = Field(default_factory=list)
    confidence: FactConfidence = "medium"
    status: FactStatus = "confirmed"


class Figure(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    value_text: str
    source_ids: list[str] = Field(default_factory=list)
    notes: str = ""


class LegalOutcome(BaseModel):
    model_config = ConfigDict(extra="ignore")

    description: str
    status: str = ""
    source_ids: list[str] = Field(default_factory=list)


class Uncertainty(BaseModel):
    model_config = ConfigDict(extra="ignore")

    description: str
    source_ids: list[str] = Field(default_factory=list)


class Contradiction(BaseModel):
    model_config = ConfigDict(extra="ignore")

    description: str
    source_ids: list[str] = Field(default_factory=list)


class VisualOpportunity(BaseModel):
    model_config = ConfigDict(extra="ignore")

    description: str
    source_ids: list[str] = Field(default_factory=list)


class ResearchDossier(BaseModel):
    model_config = ConfigDict(extra="ignore")

    schema_version: str = "1.0"
    project_id: str = ""
    topic: str
    summary: str
    entities: list[NamedRef] = Field(default_factory=list)
    locations: list[LocationRef] = Field(default_factory=list)
    timeline_events: list[TimelineEvent] = Field(default_factory=list)
    facts: list[Fact] = Field(default_factory=list)
    figures: list[Figure] = Field(default_factory=list)
    legal_outcomes: list[LegalOutcome] = Field(default_factory=list)
    uncertainties: list[Uncertainty] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)
    visual_opportunities: list[VisualOpportunity] = Field(default_factory=list)
    source_ids_used: list[str] = Field(default_factory=list)
    model: str = ""
    request_hash: str = ""
    usage: ApiUsage | None = None
    cache_hit: bool = False


class DossierValidationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    passed: bool
    fact_count: int
    unsupported_fact_count: int
    unknown_source_ids: list[str] = Field(default_factory=list)
    demoted_fact_ids: list[str] = Field(default_factory=list)
    contradictions_preserved: int = 0
    failures: list[str] = Field(default_factory=list)
