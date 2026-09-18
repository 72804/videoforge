from __future__ import annotations

import json
import re
from typing import Any

from docprod.audio.script import tokenize_display
from docprod.exceptions import SemanticPlannerError
from docprod.planning.semantic_models import (
    SEMANTIC_PLANNER_PROMPT_VERSION,
    SemanticIntentSet,
    SemanticSceneIntent,
)
from docprod.research.evidence import evidence_catalog_rows
from docprod.research.models import ResearchDossier, TopicSpec
from docprod.writing.models import NarrationScript

SEMANTIC_PLANNER_INSTRUCTIONS = (
    "You are a documentary visual planner. You do not invent facts.\n"
    "Given a sourced Turkish narration and an evidence dossier, propose visual scene intents.\n"
    "\nRules:\n"
    "- No web search. Use only the provided script and dossier.\n"
    "- Cover the entire narration with contiguous word spans (0-based start, exclusive end).\n"
    "- Aim for about 70-110 intents for a ~6 minute episode. Semantic cuts beat a fixed cadence.\n"
    "- Target roughly 2.5-6 seconds of speech per intent. Avoid tiny meaningless cuts.\n"
    "- Distinguish factual depiction vs generic reenactment.\n"
    "- Named real people: prefer archive/photograph/document/news/map. "
    "Do not invent their appearance.\n"
    "- Generic warehouse/barrel/inventory/transport reenactments are allowed as generic_only.\n"
    "- Maps must show spatial relationship or movement, not decoration. "
    "Do not claim an exact unsourced truck route.\n"
    "- Disputed figures must be labeled approximate or shown as a range.\n"
    "- Documents/court graphics are stylized summaries, never fake authentic records.\n"
    "- Alternate visual forms. Do not stack the same subject.\n"
    "- reasoning_summary is a short production rationale, not hidden chain-of-thought.\n"
    "- Return JSON only: {\"intents\":[...]}.\n"
)


def semantic_planner_json_schema() -> dict[str, Any]:
    return {
        "type": "json_schema",
        "name": "semantic_scene_intents",
        "strict": False,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["intents"],
            "properties": {
                "intents": {"type": "array", "items": {"type": "object"}},
            },
        },
    }


def planner_input_text(
    topic: TopicSpec,
    script: NarrationScript,
    dossier: ResearchDossier,
    registry_rows: list[str] | None = None,
) -> str:
    words = tokenize_display(script.full_narration)
    beats = [
        {
            "beat_id": beat.beat_id,
            "chapter": beat.chapter,
            "purpose": beat.purpose,
            "claim_ids": beat.claim_ids,
            "source_ids": beat.source_ids,
            "narration": beat.narration,
        }
        for beat in script.beats
    ]
    chapters = [
        {"chapter_id": item.chapter_id, "title": item.title, "purpose": item.purpose}
        for item in script.outline.chapters
    ]
    slim_dossier = {
        "topic": dossier.topic,
        "summary": dossier.summary,
        "entities": [item.model_dump(mode="json") for item in dossier.entities],
        "locations": [item.model_dump(mode="json") for item in dossier.locations],
        "timeline_events": [item.model_dump(mode="json") for item in dossier.timeline_events],
        "facts": [item.model_dump(mode="json") for item in dossier.facts],
        "figures": [item.model_dump(mode="json") for item in dossier.figures],
        "legal_outcomes": [item.model_dump(mode="json") for item in dossier.legal_outcomes],
        "uncertainties": [item.model_dump(mode="json") for item in dossier.uncertainties],
        "contradictions": [item.model_dump(mode="json") for item in dossier.contradictions],
        "visual_opportunities": [
            item.model_dump(mode="json") for item in dossier.visual_opportunities
        ],
        "source_ids_used": dossier.source_ids_used,
    }
    catalog = ""
    if registry_rows:
        catalog = "EVIDENCE_SOURCES:\n" + "\n".join(registry_rows) + "\n\n"
    return (
        f"PROMPT_VERSION={SEMANTIC_PLANNER_PROMPT_VERSION}\n"
        f"TOPIC={topic.topic}\n"
        f"LANGUAGE={topic.language}\n"
        f"TARGET_RUNTIME_MINUTES={topic.target_runtime_minutes}\n"
        f"SCRIPT_WORD_COUNT={len(words)}\n"
        f"WORDS_PER_MINUTE=145\n"
        "WORD_INDEXING=0-based start, exclusive end, covering 0..WORD_COUNT\n"
        "VISUAL_STYLE=restrained Canadian documentary; no fake historical photographs "
        "of named people; generic reenactment allowed for unsourced actions.\n\n"
        f"{catalog}"
        f"CHAPTERS:\n{json.dumps(chapters, ensure_ascii=False)}\n\n"
        f"BEATS:\n{json.dumps(beats, ensure_ascii=False)}\n\n"
        f"FULL_NARRATION:\n{script.full_narration}\n\n"
        f"DOSSIER:\n{json.dumps(slim_dossier, ensure_ascii=False)}\n"
    )


def evidence_rows_for_planner(dossier: ResearchDossier, registry: Any) -> list[str]:
    from docprod.research.models import SourceRegistry

    if not isinstance(registry, SourceRegistry):
        return []
    return [
        f"{item.source_id}\t{item.quality_tier}\t{item.title or item.domain}"
        for item in evidence_catalog_rows(registry)
    ]


def parse_semantic_intents(
    text: str,
    *,
    project_id: str,
    model: str,
    request_hash: str,
    word_count: int,
) -> SemanticIntentSet:
    payload = _parse_json_object(text)
    raw_intents = payload.get("intents") or payload.get("scenes") or []
    intents: list[SemanticSceneIntent] = []
    for index, item in enumerate(raw_intents, start=1):
        if not isinstance(item, dict):
            continue
        coerced = dict(item)
        if "intent_id" not in coerced:
            coerced["intent_id"] = str(coerced.get("id") or f"I{index:03d}")
        if "chapter" not in coerced:
            coerced["chapter"] = str(coerced.get("chapter_id") or coerced.get("section") or "")
        if "preferred_source_type" not in coerced:
            coerced["preferred_source_type"] = _map_source_type(
                coerced.get("source_type") or coerced.get("form") or ""
            )
        if "visual_subject" not in coerced:
            coerced["visual_subject"] = str(
                coerced.get("visual_intent") or coerced.get("subject") or ""
            )[:160]
        if "visual_description" not in coerced and coerced.get("visual_intent"):
            coerced["visual_description"] = str(coerced.get("visual_intent"))
        if "reenactment_freedom" not in coerced:
            coerced["reenactment_freedom"] = _map_freedom(coerced.get("factuality"))
        if "historical_specificity" not in coerced:
            coerced["historical_specificity"] = _map_specificity(coerced.get("factuality"))
        if "movement_need" not in coerced:
            coerced["movement_need"] = _map_movement(
                coerced.get("preferred_source_type"),
                coerced.get("visual_subject") or coerced.get("visual_intent"),
            )
        if coerced.get("preferred_source_type") == "ai_reenactment":
            freedom = str(coerced.get("reenactment_freedom") or "generic_only")
            if not coerced.get("reenactment_type"):
                coerced["reenactment_type"] = (
                    "historically_constrained" if freedom == "constrained" else "generic"
                )
        start = int(
            coerced.get("narration_start_word")
            if coerced.get("narration_start_word") is not None
            else coerced.get("start")
            if coerced.get("start") is not None
            else coerced.get("start_word")
            or 0
        )
        end = int(
            coerced.get("narration_end_word")
            if coerced.get("narration_end_word") is not None
            else coerced.get("end")
            if coerced.get("end") is not None
            else coerced.get("end_word")
            or 0
        )
        coerced["narration_start_word"] = start
        coerced["narration_end_word"] = end
        intents.append(SemanticSceneIntent.model_validate(coerced))
    if not intents:
        raise SemanticPlannerError("Semantic planner returned no intents")
    return SemanticIntentSet(
        project_id=project_id,
        model=model,
        request_hash=request_hash,
        intents=intents,
    )


_FORM_MAP = {
    "archive": "archive",
    "location/archive": "archive",
    "stock": "stock_video",
    "stock_video": "stock_video",
    "graphic": "infographic",
    "graphic/detail": "stock_video",
    "infographic": "infographic",
    "document": "document",
    "document_graphic": "document",
    "newspaper": "newspaper",
    "map": "map",
    "generic_reenactment": "ai_reenactment",
    "ai_reenactment": "ai_reenactment",
    "reenactment": "ai_reenactment",
    "photograph": "photograph",
    "title_card": "text_card",
    "text_card": "text_card",
    "warehouse_detail": "stock_video",
    "mixed": "mixed",
}


def _map_source_type(value: object) -> str:
    key = str(value or "").strip().lower()
    if key in _FORM_MAP:
        return _FORM_MAP[key]
    if "map" in key:
        return "map"
    if "document" in key or "court" in key or "newspaper" in key:
        return "document"
    if "reenact" in key:
        return "ai_reenactment"
    if "archive" in key or "photo" in key:
        return "archive"
    if "graphic" in key or "chart" in key:
        return "infographic"
    if "card" in key:
        return "text_card"
    return "stock_video"


def _map_freedom(value: object) -> str:
    key = str(value or "").strip().lower()
    if key in {"generic_only", "generic"}:
        return "generic_only"
    if key in {"constrained", "historically_constrained"}:
        return "constrained"
    if key in {"avoid", "factual_depiction", "stylized_summary"}:
        return "avoid"
    return "generic_only"


def _map_movement(source_type: object, visual: object) -> str:
    blob = f"{source_type} {visual}".lower()
    if any(
        token in blob
        for token in ("kamyon", "truck", "transport", "sevkiyat", "walk", "hareket")
    ):
        return "high"
    if str(source_type) == "ai_reenactment":
        return "high"
    if str(source_type) in {"map", "document", "infographic", "text_card"}:
        return "none"
    return "low"


def _map_specificity(value: object) -> str:
    key = str(value or "").strip().lower()
    if key in {"factual_depiction", "exact"}:
        return "exact_place_or_object"
    if key in {"stylized_summary", "approximate"}:
        return "approximate_period"
    return "generic"


def _parse_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", stripped, re.DOTALL)
    if fenced:
        stripped = fenced.group(1)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end <= start:
        raise SemanticPlannerError("Semantic planner response was not JSON")
    data = json.loads(stripped[start : end + 1])
    if not isinstance(data, dict):
        raise SemanticPlannerError("Semantic planner JSON must be an object")
    return data
