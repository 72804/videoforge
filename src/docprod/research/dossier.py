from __future__ import annotations

import json
import re
from typing import Any

from docprod.exceptions import DossierValidationError
from docprod.research.models import (
    DOSSIER_PROMPT_VERSION,
    Contradiction,
    DossierValidationSummary,
    Fact,
    Figure,
    ResearchDossier,
    SourceRegistry,
)

DOSSIER_INSTRUCTIONS = (
    "You extract a documentary evidence dossier from a sourced research report.\n"
    "\nRules:\n"
    "- Use only the provided report and source registry.\n"
    "- Never invent dates, quotes, motives, thoughts, or legal outcomes.\n"
    "- Distinguish charged, accused, and convicted.\n"
    "- Preserve disagreements as contradictions; do not pick the more dramatic number.\n"
    "- Every fact, figure, timeline event, and legal outcome must include "
    "source_ids from the registry (S001, S002, ...).\n"
    "- If a claim is weakly supported, mark status uncertain or disputed.\n"
    "- visual_opportunities describe possible documentary images "
    "(warehouses, barrels, maps, court records) without writing visual prompts.\n"
    "- Return JSON only matching the schema.\n"
)


def dossier_json_schema() -> dict[str, Any]:
    return {
        "type": "json_schema",
        "name": "research_dossier",
        "strict": False,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "topic",
                "summary",
                "entities",
                "locations",
                "timeline_events",
                "facts",
                "figures",
                "legal_outcomes",
                "uncertainties",
                "contradictions",
                "visual_opportunities",
                "source_ids_used",
            ],
            "properties": {
                "topic": {"type": "string"},
                "summary": {"type": "string"},
                "entities": {"type": "array", "items": {"type": "object"}},
                "locations": {"type": "array", "items": {"type": "object"}},
                "timeline_events": {"type": "array", "items": {"type": "object"}},
                "facts": {"type": "array", "items": {"type": "object"}},
                "figures": {"type": "array", "items": {"type": "object"}},
                "legal_outcomes": {"type": "array", "items": {"type": "object"}},
                "uncertainties": {"type": "array", "items": {"type": "object"}},
                "contradictions": {"type": "array", "items": {"type": "object"}},
                "visual_opportunities": {"type": "array", "items": {"type": "object"}},
                "source_ids_used": {"type": "array", "items": {"type": "string"}},
            },
        },
    }


def parse_dossier_json(
    text: str, *, project_id: str, model: str, request_hash: str
) -> ResearchDossier:
    payload = coerce_dossier_payload(_parse_json_object(text))
    payload["project_id"] = project_id
    payload["model"] = model
    payload["request_hash"] = request_hash
    return ResearchDossier.model_validate(payload)


_STATUS_MAP = {
    "documented": "attributed",
    "documented with attribution": "attributed",
    "established": "confirmed",
    "alleged": "attributed",
    "reported": "attributed",
    "claimed": "attributed",
    "unknown": "uncertain",
    "contested": "disputed",
}


def _status(value: Any) -> str:
    text = str(value or "").strip().casefold()
    if text in {"confirmed", "attributed", "disputed", "uncertain"}:
        return text
    for key, mapped in _STATUS_MAP.items():
        if key in text:
            return mapped
    return "attributed"


def _ids(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).startswith("S")]
    if isinstance(value, str) and value.startswith("S"):
        return [value]
    return []


def _text(*parts: Any) -> str:
    bits = [str(part).strip() for part in parts if part]
    return " — ".join(bits)


def coerce_dossier_payload(payload: dict[str, Any]) -> dict[str, Any]:
    events = []
    for index, raw in enumerate(payload.get("timeline_events") or [], start=1):
        if not isinstance(raw, dict):
            continue
        events.append(
            {
                "event_id": raw.get("event_id") or f"E{index:03d}",
                "date_or_range": raw.get("date_or_range") or raw.get("date") or "",
                "description": (
                    raw.get("description") or raw.get("event") or raw.get("summary") or ""
                ),
                "source_ids": _ids(raw.get("source_ids")),
            }
        )
    facts = []
    for index, raw in enumerate(payload.get("facts") or [], start=1):
        if not isinstance(raw, dict):
            continue
        facts.append(
            {
                "fact_id": raw.get("fact_id") or f"F{index:03d}",
                "claim": raw.get("claim") or raw.get("statement") or raw.get("text") or "",
                "source_ids": _ids(raw.get("source_ids")),
                "confidence": raw.get("confidence")
                if raw.get("confidence") in {"high", "medium", "low"}
                else "medium",
                "status": _status(raw.get("status")),
            }
        )
    figures = []
    for raw in payload.get("figures") or []:
        if not isinstance(raw, dict):
            continue
        figures.append(
            {
                "name": raw.get("name") or raw.get("subject") or raw.get("label") or "",
                "value_text": str(
                    raw.get("value_text") or raw.get("value") or raw.get("amount") or ""
                ),
                "source_ids": _ids(raw.get("source_ids")),
                "notes": str(raw.get("notes") or ""),
            }
        )
    legal = []
    for raw in payload.get("legal_outcomes") or []:
        if not isinstance(raw, dict):
            continue
        legal.append(
            {
                "description": raw.get("description")
                or _text(
                    raw.get("person"),
                    raw.get("outcome"),
                    raw.get("status"),
                    raw.get("sentence"),
                ),
                "status": str(raw.get("status") or raw.get("outcome") or ""),
                "source_ids": _ids(raw.get("source_ids")),
            }
        )
    uncertainties = []
    for raw in payload.get("uncertainties") or []:
        if not isinstance(raw, dict):
            continue
        uncertainties.append(
            {
                "description": raw.get("description") or raw.get("issue") or raw.get("note") or "",
                "source_ids": _ids(raw.get("source_ids")),
            }
        )
    contradictions = []
    for raw in payload.get("contradictions") or []:
        if not isinstance(raw, dict):
            continue
        contradictions.append(
            {
                "description": raw.get("description")
                or _text(raw.get("topic"), raw.get("details"), raw.get("summary")),
                "source_ids": _ids(raw.get("source_ids")),
            }
        )
    visuals = []
    for raw in payload.get("visual_opportunities") or []:
        if not isinstance(raw, dict):
            continue
        visuals.append(
            {
                "description": (
                    raw.get("description") or raw.get("opportunity") or raw.get("type") or ""
                ),
                "source_ids": _ids(raw.get("source_ids")),
            }
        )
    payload = dict(payload)
    payload["timeline_events"] = events
    payload["facts"] = facts
    payload["figures"] = figures
    payload["legal_outcomes"] = legal
    payload["uncertainties"] = uncertainties
    payload["contradictions"] = contradictions
    payload["visual_opportunities"] = visuals
    payload.setdefault("entities", [])
    payload.setdefault("locations", [])
    payload.setdefault("source_ids_used", [])
    payload.setdefault("topic", "")
    payload.setdefault("summary", "")
    return payload


def _parse_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", stripped, re.DOTALL)
    if fenced:
        stripped = fenced.group(1)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise DossierValidationError("Dossier response was not JSON")
    data = json.loads(stripped[start : end + 1])
    if not isinstance(data, dict):
        raise DossierValidationError("Dossier JSON must be an object")
    return data


def _known_ids(registry: SourceRegistry) -> set[str]:
    return {item.source_id for item in registry.sources}


def _collect_ids(*groups: list[str]) -> list[str]:
    seen: list[str] = []
    for group in groups:
        for item in group:
            if item not in seen:
                seen.append(item)
    return seen


def validate_dossier(
    dossier: ResearchDossier,
    registry: SourceRegistry,
    *,
    require: bool = True,
) -> tuple[ResearchDossier, DossierValidationSummary]:
    known = _known_ids(registry)
    unknown: list[str] = []
    demoted: list[str] = []
    facts: list[Fact] = []
    for fact in dossier.facts:
        bad = [sid for sid in fact.source_ids if sid not in known]
        unknown.extend(bad)
        if not fact.source_ids or bad:
            demoted.append(fact.fact_id)
            facts.append(
                fact.model_copy(
                    update={
                        "status": "uncertain",
                        "confidence": "low",
                        "source_ids": fact.source_ids,
                    }
                )
            )
            continue
        facts.append(fact)

    def check_ids(ids: list[str]) -> list[str]:
        bad = [sid for sid in ids if sid not in known]
        unknown.extend(bad)
        return ids

    for event in dossier.timeline_events:
        check_ids(event.source_ids)
    for figure in dossier.figures:
        check_ids(figure.source_ids)
    for item in dossier.legal_outcomes:
        check_ids(item.source_ids)

    contradictions = list(dossier.contradictions)
    contradictions.extend(_figure_contradictions(dossier.figures))
    usable_facts = [fact for fact in facts if fact.source_ids and fact.fact_id not in demoted]
    unsupported = len(demoted)
    failures: list[str] = []
    if unknown:
        failures.append("Unknown source IDs: " + ", ".join(sorted(set(unknown))))
    if not usable_facts:
        failures.append("No sourced usable facts remain")
    updated = dossier.model_copy(
        update={
            "facts": facts,
            "contradictions": contradictions,
            "source_ids_used": _collect_ids(
                dossier.source_ids_used,
                *[fact.source_ids for fact in usable_facts],
            ),
        }
    )
    summary = DossierValidationSummary(
        passed=not failures,
        fact_count=len(usable_facts),
        unsupported_fact_count=unsupported,
        unknown_source_ids=sorted(set(unknown)),
        demoted_fact_ids=demoted,
        contradictions_preserved=len(contradictions),
        failures=failures,
    )
    if require and not summary.passed:
        raise DossierValidationError("; ".join(failures) or "Dossier validation failed")
    return updated, summary


def _figure_contradictions(figures: list[Figure]) -> list[Contradiction]:
    by_name: dict[str, list[Figure]] = {}
    for item in figures:
        key = item.name.strip().casefold()
        by_name.setdefault(key, []).append(item)
    extra: list[Contradiction] = []
    for name, group in by_name.items():
        values = {item.value_text.strip() for item in group}
        if len(values) > 1:
            extra.append(
                Contradiction(
                    description=(
                        f"Conflicting figures for {group[0].name}: " + "; ".join(sorted(values))
                    ),
                    source_ids=_collect_ids(*[item.source_ids for item in group]),
                )
            )
    return extra


def dossier_input_text(report: str, registry: SourceRegistry) -> str:
    from docprod.research.evidence import evidence_catalog_rows

    rows = evidence_catalog_rows(registry)
    catalog = "\n".join(
        f"{item.source_id}\t{item.quality_tier}\t{item.title or item.domain}\t{item.url}"
        for item in rows
    )
    return (
        f"PROMPT_VERSION={DOSSIER_PROMPT_VERSION}\n\n"
        "## Source registry\n"
        f"{catalog}\n\n"
        "## Research report\n"
        f"{report}\n"
    )
