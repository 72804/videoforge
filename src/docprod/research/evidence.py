from __future__ import annotations

from typing import Any

from docprod.research.models import ResearchDossier, SourceRecord, SourceRegistry
from docprod.writing.models import NarrationScript

CONTEXT_TIER_A_CAP = 8


def collect_referenced_source_ids(
    dossier: ResearchDossier | None,
    script: NarrationScript | None = None,
) -> set[str]:
    ids: set[str] = set()
    if dossier is None:
        return ids
    ids.update(dossier.source_ids_used)
    groups: list[Any] = [
        dossier.facts,
        dossier.timeline_events,
        dossier.figures,
        dossier.legal_outcomes,
        dossier.uncertainties,
        dossier.contradictions,
        dossier.entities,
        dossier.locations,
        dossier.visual_opportunities,
    ]
    for group in groups:
        for item in group:
            ids.update(getattr(item, "source_ids", []) or [])
    if script is not None:
        for beat in script.beats:
            ids.update(beat.source_ids)
    return {item for item in ids if item}


def apply_evidence_set(
    registry: SourceRegistry,
    *,
    dossier: ResearchDossier | None,
    script: NarrationScript | None = None,
    extra_tier_a_cap: int = CONTEXT_TIER_A_CAP,
) -> SourceRegistry:
    """Keep every discovered URL. Mark a smaller evidence set for downstream use."""
    used = collect_referenced_source_ids(dossier, script)
    known = {item.source_id: item for item in registry.sources}
    evidence: list[str] = [sid for sid in sorted(used) if sid in known]
    extra = 0
    for item in registry.sources:
        if extra >= extra_tier_a_cap:
            break
        if item.source_id in used:
            continue
        if item.quality_tier == "A":
            evidence.append(item.source_id)
            extra += 1
    return registry.model_copy(update={"evidence_source_ids": evidence})


def evidence_catalog_rows(registry: SourceRegistry) -> list[SourceRecord]:
    records = registry.evidence_records()
    if records:
        return records
    return [item for item in registry.sources if item.quality_tier != "low"]
