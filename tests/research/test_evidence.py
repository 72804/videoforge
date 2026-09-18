from __future__ import annotations

from datetime import UTC, datetime

from docprod.research.evidence import apply_evidence_set
from docprod.research.models import Fact, ResearchDossier, SourceRecord, SourceRegistry
from docprod.writing.models import NarrationBeat, NarrationScript, StoryOutline


def _source(sid: str, url: str, tier: str) -> SourceRecord:
    return SourceRecord(
        source_id=sid,
        url=url,
        title=sid,
        domain=url.split("/")[2],
        accessed_at=datetime(2026, 1, 1, tzinfo=UTC),
        quality_tier=tier,  # type: ignore[arg-type]
        quality_reason="test",
    )


def test_evidence_set_excludes_unused_low_quality() -> None:
    registry = SourceRegistry(
        project_id="p",
        sources=[
            _source("S001", "https://canlii.org/a", "A"),
            _source("S002", "https://www.cbc.ca/a", "B"),
            _source("S003", "https://www.reddit.com/r/x", "low"),
            _source("S004", "https://random-blog.example/post", "low"),
        ],
    )
    dossier = ResearchDossier(
        project_id="p",
        topic="t",
        summary="s",
        facts=[
            Fact(
                fact_id="F001",
                claim="x",
                source_ids=["S001"],
                confidence="high",
                status="confirmed",
            )
        ],
        source_ids_used=["S001"],
    )
    script = NarrationScript(
        project_id="p",
        language="tr",
        outline=StoryOutline(),
        beats=[
            NarrationBeat(
                beat_id="B001",
                narration="Depo.",
                claim_ids=["F001"],
                source_ids=["S002"],
            )
        ],
        full_narration="Depo.",
    )
    updated = apply_evidence_set(registry, dossier=dossier, script=script, extra_tier_a_cap=0)
    assert len(registry.sources) == 4
    assert updated.discovered_count() == 4
    assert set(updated.evidence_source_ids) == {"S001", "S002"}
    assert "S003" not in updated.evidence_source_ids
    assert [item.source_id for item in updated.evidence_records()] == ["S001", "S002"]
