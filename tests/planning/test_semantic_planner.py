from __future__ import annotations

from docprod.audio.script import tokenize_display
from docprod.models.enums import AssetStrategy
from docprod.planning.semantic_compiler import compile_semantic_plan, map_strategy
from docprod.planning.semantic_models import SemanticIntentSet, SemanticSceneIntent
from docprod.planning.semantic_planner import parse_semantic_intents
from docprod.planning.semantic_validation import hallucination_warnings
from docprod.research.models import (
    Fact,
    Figure,
    NamedRef,
    ResearchDossier,
    Uncertainty,
)
from docprod.writing.models import NarrationBeat, NarrationScript, StoryOutline


def _script(words: int = 40) -> NarrationScript:
    text = " ".join(["kelime"] * words)
    return NarrationScript(
        project_id="maple_heist_canary",
        language="tr",
        outline=StoryOutline(),
        beats=[
            NarrationBeat(
                beat_id="B001",
                narration=text,
                claim_ids=["F001"],
                source_ids=["S001"],
                chapter="HOOK",
            )
        ],
        full_narration=text,
        word_count=words,
    )


def _dossier() -> ResearchDossier:
    return ResearchDossier(
        project_id="maple_heist_canary",
        topic="heist",
        summary="Warehouse loss in 2012.",
        entities=[NamedRef(name="Michel Gauvreau", role="auditor", source_ids=["S001"])],
        facts=[
            Fact(
                fact_id="F001",
                claim="Barrels were missing.",
                source_ids=["S001"],
                confidence="high",
                status="confirmed",
            )
        ],
        figures=[
            Figure(
                name="loss",
                value_text="18.7 million",
                source_ids=["S001"],
                notes="sources disagree 18 or 18.7",
            )
        ],
        uncertainties=[Uncertainty(description="Exact quantity stolen", source_ids=["S001"])],
        source_ids_used=["S001"],
    )


def _intent(**kwargs: object) -> SemanticSceneIntent:
    payload: dict[str, object] = {
        "intent_id": "I001",
        "chapter": "HOOK",
        "narration_span": "kelime",
        "narration_start_word": 0,
        "narration_end_word": 40,
        "visual_subject": "maple syrup barrels",
        "visual_action": "stored in rows",
        "visual_environment": "warehouse",
        "visual_purpose": "establish the reserve",
        "preferred_source_type": "stock_video",
        "movement_need": "low",
        "historical_specificity": "generic",
        "claim_ids": ["F001"],
        "source_ids": ["S001"],
        "reenactment_freedom": "generic_only",
        "reasoning_summary": "Generic barrels, not a named person.",
        "image_prompt_seed": "warehouse barrels",
        "stock_query_seed": "maple syrup barrels warehouse",
        "archive_search_seed": "Great Canadian Maple Syrup Heist 2012 Quebec warehouse",
        "graphic_brief": "",
    }
    payload.update(kwargs)
    return SemanticSceneIntent.model_validate(payload)


def test_semantic_scene_structured_parsing() -> None:
    parsed = parse_semantic_intents(
        """
        {"intents": [{"intent_id": "I001", "preferred_source_type": "ai_reenactment",
          "reenactment_freedom": "generic_only", "narration_start_word": 0,
          "narration_end_word": 10, "visual_subject": "inspector"}]}
        """,
        project_id="p",
        model="gpt-5.6-luna",
        request_hash="h",
        word_count=10,
    )
    assert parsed.intents[0].reenactment_type == "generic"
    assert parsed.intents[0].preferred_source_type == "ai_reenactment"
    alias = parse_semantic_intents(
        '{"intents":[{"start":0,"end":10,"form":"generic_reenactment","visual_intent":"x"}]}',
        project_id="p",
        model="m",
        request_hash="h",
        word_count=10,
    )
    assert alias.intents[0].narration_start_word == 0
    assert alias.intents[0].narration_end_word == 10
    assert alias.intents[0].preferred_source_type == "ai_reenactment"


def test_spans_cover_script_and_sceneplan_compatible() -> None:
    script = _script(40)
    intents = SemanticIntentSet(project_id=script.project_id, intents=[_intent()])
    plan, diag = compile_semantic_plan(intents, script=script, dossier=_dossier())
    words = tokenize_display(script.full_narration)
    covered = " ".join(scene.narration for scene in plan.scenes).split()
    assert covered == words
    starts = [scene.start for scene in plan.scenes]
    assert starts == sorted(starts)
    for prev, curr in zip(plan.scenes, plan.scenes[1:], strict=False):
        assert abs(curr.start - prev.end) < 1e-6
    assert 1.5 <= diag.min_scene_duration <= diag.max_scene_duration <= 8.0
    assert plan.scenes[0].id == "scene_0001"
    assert plan.total_duration == plan.scenes[-1].end


def test_source_and_claim_ids_valid_and_seeds_stored() -> None:
    script = _script(20)
    intent = _intent(narration_end_word=20)
    plan, diag = compile_semantic_plan(
        SemanticIntentSet(project_id=script.project_id, intents=[intent]),
        script=script,
        dossier=_dossier(),
    )
    meta = plan.scenes[0].metadata
    assert meta["claim_ids"] == ["F001"]
    assert meta["source_ids"] == ["S001"]
    assert meta["stock_query_seed"]
    assert meta["archive_search_seed"]
    assert meta["image_prompt_seed"]
    assert diag.sources_referenced >= 1


def test_named_people_prefer_archive_not_invented_ai() -> None:
    intent = _intent(
        preferred_source_type="ai_reenactment",
        historical_specificity="exact_person_or_event",
        visual_subject="Michel Gauvreau",
        image_prompt_seed="Michel Gauvreau close-up portrait",
    )
    assert map_strategy(intent) is AssetStrategy.archive_image
    flags = hallucination_warnings(
        scene_id="scene_0001",
        intent=intent,
        strategy=AssetStrategy.ai_image,
        dossier=_dossier(),
        script=_script(20),
    )
    assert any(item.code == "named_person_invented_appearance" for item in flags)


def test_unsourced_historic_and_disputed_and_map_and_fake_doc() -> None:
    dossier = _dossier()
    script = _script(20)
    historic = _intent(
        historical_specificity="exact_place_or_object",
        claim_ids=[],
        source_ids=[],
        visual_description="exact 2012 barrel lid serial number 9921",
    )
    flags = hallucination_warnings(
        scene_id="s",
        intent=historic,
        strategy=AssetStrategy.ai_image,
        dossier=dossier,
        script=script,
    )
    assert any(item.code == "unsourced_historic_detail" for item in flags)
    graphic = _intent(
        preferred_source_type="infographic",
        graphic_brief="Loss is exactly 18.7 million",
    )
    flags = hallucination_warnings(
        scene_id="s",
        intent=graphic,
        strategy=AssetStrategy.generated_graphic,
        dossier=dossier,
        script=script,
    )
    assert any(item.code == "disputed_figure_as_exact" for item in flags)
    mapped = _intent(graphic_brief="Map of the exact route the truck took")
    flags = hallucination_warnings(
        scene_id="s",
        intent=mapped,
        strategy=AssetStrategy.map,
        dossier=dossier,
        script=script,
    )
    assert any(item.code == "map_overprecision" for item in flags)
    fake = _intent(graphic_brief="authentic court record facsimile")
    flags = hallucination_warnings(
        scene_id="s",
        intent=fake,
        strategy=AssetStrategy.document,
        dossier=dossier,
        script=script,
    )
    assert any(item.code == "fake_authentic_document" for item in flags)


def test_reenactment_metadata_and_generic_allowed() -> None:
    script = _script(12)
    intent = _intent(
        narration_end_word=12,
        preferred_source_type="ai_reenactment",
        reenactment_freedom="generic_only",
        reenactment_type="generic",
        historical_specificity="generic",
        visual_subject="inventory inspector",
        movement_need="low",
    )
    plan, _diag = compile_semantic_plan(
        SemanticIntentSet(project_id=script.project_id, intents=[intent]),
        script=script,
        dossier=_dossier(),
    )
    assert plan.scenes[0].asset_strategy is AssetStrategy.ai_image
    assert plan.scenes[0].metadata["reenactment_type"] == "generic"
    assert plan.scenes[0].generation.image_prompt


def test_document_stylized_not_authentic() -> None:
    script = _script(10)
    intent = _intent(
        narration_end_word=10,
        preferred_source_type="document",
        visual_purpose="court outcome summary",
    )
    plan, _diag = compile_semantic_plan(
        SemanticIntentSet(project_id=script.project_id, intents=[intent]),
        script=script,
        dossier=_dossier(),
    )
    assert plan.scenes[0].asset_strategy is AssetStrategy.archive_image
    assert "not a fake authentic" not in plan.scenes[0].visual_intent.lower()
    assert not plan.scenes[0].metadata.get("stylized_graphic_not_authentic")


def test_ai_video_cap_and_consecutive_limit() -> None:
    script = _script(100)
    intents = []
    for index in range(10):
        start = index * 10
        intents.append(
            _intent(
                intent_id=f"I{index:03d}",
                narration_start_word=start,
                narration_end_word=start + 10,
                preferred_source_type="ai_reenactment",
                movement_need="high",
                visual_subject=f"transport {index}",
            )
        )
    plan, diag = compile_semantic_plan(
        SemanticIntentSet(project_id=script.project_id, intents=intents),
        script=script,
        dossier=_dossier(),
    )
    assert diag.ai_video_fraction <= 0.10 + 1e-9
    run = 0
    max_run = 0
    for scene in plan.scenes:
        if scene.asset_strategy is AssetStrategy.ai_image_to_video:
            run += 1
            max_run = max(max_run, run)
        else:
            run = 0
    assert max_run <= 2


def test_repetition_and_diversity_warnings() -> None:
    from docprod.planning.semantic_validation import diversity_warnings, repetition_warnings

    subjects = ["barrels"] * 8
    strategies = [AssetStrategy.ai_image] * 8
    reps = repetition_warnings(subjects, strategies)
    divs = diversity_warnings(strategies)
    assert any(item.code == "subject_repetition" for item in reps)
    assert any(item.code == "ai_still_run" for item in divs)


def test_planner_demo_profile_untouched() -> None:
    from docprod.planning.profile import DOCUMENTARY_V1, get_profile

    profile = get_profile("documentary_v1")
    assert profile.max_ai_video_fraction == DOCUMENTARY_V1.max_ai_video_fraction
    assert get_profile("documentary_v1").name == "documentary_v1"


def test_punctuation_survives_compile_into_scene_narration() -> None:
    text = "Quebec'te bir depo. Envanter, rapor; 'şurup' kayıptı."
    words = tokenize_display(text)
    script = NarrationScript(
        project_id="maple_heist_canary",
        language="tr",
        outline=StoryOutline(),
        beats=[
            NarrationBeat(
                beat_id="B001",
                narration=text,
                claim_ids=["F001"],
                source_ids=["S001"],
                chapter="HOOK",
            )
        ],
        full_narration=text,
        word_count=len(words),
    )
    intent = _intent(narration_end_word=len(words), narration_span=text)
    plan, _diag = compile_semantic_plan(
        SemanticIntentSet(project_id=script.project_id, intents=[intent]),
        script=script,
        dossier=_dossier(),
    )
    joined = " ".join(scene.narration for scene in plan.scenes)
    assert "." in joined
    assert "," in joined
    assert ";" in joined
    assert "'" in joined
    from docprod.audio.script import build_canonical_script, tts_input_text

    tts = tts_input_text(build_canonical_script(plan))
    assert "." in tts and "," in tts and ";" in tts
