from __future__ import annotations

import pytest

from docprod.exceptions import ScriptValidationError
from docprod.research.models import Fact, ResearchDossier
from docprod.writing.documentary import parse_script_json
from docprod.writing.models import NarrationBeat, NarrationScript, StoryChapter, StoryOutline
from docprod.writing.validation import validate_script


def _dossier() -> ResearchDossier:
    return ResearchDossier(
        project_id="p",
        topic="heist",
        summary="A warehouse lost barrels in 2012.",
        facts=[
            Fact(
                fact_id="F001",
                claim="Thousands of barrels were missing from the warehouse.",
                source_ids=["S001"],
                confidence="high",
                status="confirmed",
            )
        ],
        source_ids_used=["S001"],
    )


def test_beats_keep_ids_and_reject_invention() -> None:
    good = parse_script_json(
        """
        {"outline": {"logline": "heist", "chapters": [{"chapter_id": "hook", "title": "Hook",
          "purpose": "open", "beat_ids": ["b01"]}]},
         "beats": [{"beat_id": "b01", "narration": "2012 yılında depoda binlerce varil eksikti.",
          "claim_ids": ["F001"], "source_ids": ["S001"], "chapter": "hook", "purpose": "fact"}]}
        """,
        project_id="p",
        language="tr",
        model="gpt-5.6-terra",
        request_hash="h",
    )
    script, summary = validate_script(good, _dossier(), require=True, word_min=1, word_max=50)
    assert summary.passed
    assert script.beats[0].claim_ids == ["F001"]
    assert script.beats[0].source_ids == ["S001"]
    bad = NarrationScript(
        project_id="p",
        language="tr",
        outline=StoryOutline(
            logline="x",
            chapters=[StoryChapter(chapter_id="hook", title="h", purpose="p", beat_ids=["b02"])],
        ),
        beats=[
            NarrationBeat(
                beat_id="b02",
                narration="Hırsız gece yarısı depoya sessizce girdi ve etrafına bakındı.",
                claim_ids=["F001"],
                source_ids=["S001"],
                chapter="hook",
                purpose="bad",
            )
        ],
        full_narration="Hırsız gece yarısı depoya sessizce girdi ve etrafına bakındı.",
        word_count=10,
        writer_model="gpt-5.6-terra",
        request_hash="h",
    )
    with pytest.raises(ScriptValidationError, match="Unsupported"):
        validate_script(bad, _dossier(), require=True, word_min=1, word_max=50)


def test_word_count_gate() -> None:
    script = parse_script_json(
        """
        {"outline": {"logline": "x", "chapters": []},
         "beats": [{"beat_id": "b01", "narration": "Kısa.",
          "claim_ids": ["F001"], "source_ids": ["S001"], "chapter": "hook", "purpose": "x"}]}
        """,
        project_id="p",
        language="tr",
        model="m",
        request_hash="h",
    )
    with pytest.raises(ScriptValidationError, match="Word count"):
        validate_script(script, _dossier(), require=True, word_min=850, word_max=1050)


def test_outline_structure_maps_to_chapters() -> None:
    script = parse_script_json(
        """
        {"outline": {"title": "Maple", "structure": [{"title": "HOOK", "purpose": "open"}]},
         "beats": [{"beat_id": "B001", "narration": "Depoda binlerce varil eksikti.",
          "claim_ids": ["F001"], "source_ids": ["S001"], "chapter": "HOOK", "purpose": "open"}]}
        """,
        project_id="p",
        language="tr",
        model="m",
        request_hash="h",
    )
    assert script.outline.logline == "Maple"
    assert script.outline.chapters[0].title == "HOOK"
    assert script.outline.chapters[0].beat_ids == ["B001"]
