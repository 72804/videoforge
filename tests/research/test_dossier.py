from __future__ import annotations

import json

import pytest

from docprod.exceptions import DossierValidationError
from docprod.research.citations import build_source_registry, collect_raw_sources
from docprod.research.dossier import parse_dossier_json, validate_dossier
from docprod.research.models import Fact, Figure, ResearchDossier, TimelineEvent


def _registry():
    raw = collect_raw_sources(
        annotations=[],
        web_search_sources=[
            {"url": "https://www.cbc.ca/a", "title": "CBC"},
            {"url": "https://www.reuters.com/b", "title": "Reuters"},
        ],
    )
    return build_source_registry("p", raw)


def test_parse_and_require_source_ids() -> None:
    payload = {
        "topic": "heist",
        "summary": "Theft of syrup.",
        "entities": [],
        "locations": [],
        "timeline_events": [
            {
                "event_id": "E1",
                "date_or_range": "2012",
                "description": "Discovery",
                "source_ids": ["S001"],
            }
        ],
        "facts": [
            {
                "fact_id": "F001",
                "claim": "Barrels were missing.",
                "source_ids": ["S001"],
                "confidence": "high",
                "status": "confirmed",
            },
            {
                "fact_id": "F002",
                "claim": "No source.",
                "source_ids": [],
                "confidence": "high",
                "status": "confirmed",
            },
        ],
        "figures": [],
        "legal_outcomes": [],
        "uncertainties": [
            {
                "description": "Exact barrel count varies.",
                "source_ids": ["S001", "S002"],
            }
        ],
        "contradictions": [],
        "visual_opportunities": [],
        "source_ids_used": ["S001"],
    }
    text = json.dumps(payload)
    dossier = parse_dossier_json(text, project_id="p", model="gpt-5.6-luna", request_hash="x")
    updated, summary = validate_dossier(dossier, _registry(), require=True)
    assert summary.passed
    assert summary.fact_count == 1
    assert "F002" in summary.demoted_fact_ids
    assert any(item.status == "uncertain" for item in updated.facts if item.fact_id == "F002")
    assert updated.uncertainties[0].description


def test_unknown_source_id_rejected() -> None:
    dossier = ResearchDossier(
        project_id="p",
        topic="t",
        summary="s",
        facts=[
            Fact(
                fact_id="F001",
                claim="x",
                source_ids=["S999"],
                confidence="high",
                status="confirmed",
            )
        ],
        timeline_events=[
            TimelineEvent(event_id="E1", date_or_range="2012", description="d", source_ids=["S001"])
        ],
    )
    with pytest.raises(DossierValidationError, match="Unknown source"):
        validate_dossier(dossier, _registry(), require=True)


def test_conflicting_figures_preserved() -> None:
    dossier = ResearchDossier(
        project_id="p",
        topic="t",
        summary="s",
        facts=[
            Fact(
                fact_id="F001",
                claim="Loss reported.",
                source_ids=["S001"],
                confidence="medium",
                status="attributed",
            )
        ],
        figures=[
            Figure(name="value", value_text="$18 million", source_ids=["S001"]),
            Figure(name="value", value_text="C$30 million", source_ids=["S002"]),
        ],
    )
    updated, summary = validate_dossier(dossier, _registry(), require=True)
    assert summary.passed
    assert summary.contradictions_preserved >= 1
    assert any(
        "18" in item.description and "30" in item.description for item in updated.contradictions
    )


def test_coerce_alias_fields() -> None:
    text = json.dumps(
        {
            "topic": "heist",
            "summary": "Theft",
            "entities": [],
            "locations": [],
            "timeline_events": [
                {"date": "2012", "event": "Discovery", "source_ids": ["S001"]}
            ],
            "facts": [
                {
                    "claim": "Barrels missing.",
                    "source_ids": ["S001"],
                    "status": "documented with attribution",
                }
            ],
            "figures": [{"subject": "value", "value": "$18m", "source_ids": ["S001"]}],
            "legal_outcomes": [
                {"person": "X", "outcome": "convicted", "source_ids": ["S001"]}
            ],
            "uncertainties": [{"issue": "Counts differ", "source_ids": ["S001"]}],
            "contradictions": [{"topic": "value", "details": "18 vs 30", "source_ids": ["S001"]}],
            "visual_opportunities": [],
            "source_ids_used": ["S001"],
        }
    )
    dossier = parse_dossier_json(text, project_id="p", model="m", request_hash="h")
    assert dossier.timeline_events[0].date_or_range == "2012"
    assert dossier.facts[0].status == "attributed"
    assert dossier.figures[0].name == "value"
    assert "convicted" in dossier.legal_outcomes[0].description
