from __future__ import annotations

from pathlib import Path

from docprod.models.enums import AssetStrategy, Mood, TransitionType, VisualEffect
from docprod.models.scene import GenerationSpec, Scene, ScenePlan
from docprod.pipeline.replace_explainer_visuals import (
    apply_replacement_strategies,
    is_generated_explainer_unit,
    plan_explainer_replacements,
)
from docprod.planning.models import ContentCategory
from docprod.planning.semantic_compiler import map_strategy
from docprod.planning.semantic_models import SemanticSceneIntent
from docprod.planning.strategy import preferred_strategy
from docprod.planning.visual_policy import (
    VISUAL_POLICY,
    concept_for_scene,
    dates_do_not_imply_document,
    geography_does_not_imply_map,
    legal_outcome_does_not_imply_court_graphic,
    statistics_do_not_imply_chart,
)
from docprod.production import AssetPlan, AssetUnit, PhotoSequenceAsset
from docprod.production.prompts import fallback_strategy


def _intent(**kwargs: object) -> SemanticSceneIntent:
    payload = {
        "intent_id": "I001",
        "chapter": "HOOK",
        "narration_span": "kelime",
        "narration_start_word": 0,
        "narration_end_word": 10,
        "visual_subject": "maple syrup barrels",
        "preferred_source_type": "stock_video",
        "movement_need": "low",
        "historical_specificity": "generic",
    }
    payload.update(kwargs)
    return SemanticSceneIntent.model_validate(payload)


def _scene(n: int, strategy: AssetStrategy, narration: str, subject: str) -> Scene:
    return Scene(
        id=f"scene_{n:04d}",
        start=0.0,
        end=6.2,
        duration=6.2,
        narration=narration,
        visual_intent=subject,
        asset_strategy=strategy,
        effect=VisualEffect.slow_push_in,
        transition=TransitionType.cut,
        mood=Mood.neutral,
        subtitle=narration,
        generation=GenerationSpec(),
        metadata={"visual_subject": subject, "chapter": "HOOK"},
    )


def _unit(uid: str, scenes: list[str], strategy: AssetStrategy) -> AssetUnit:
    return AssetUnit(
        asset_unit_id=uid,
        scene_ids=scenes,
        source_strategy=strategy,
        continuous_duration=6.2,
        visual_concept="x",
        status="READY_LOCAL",
    )


def test_policy_text_and_defaults() -> None:
    assert "photographic/filmic" in VISUAL_POLICY
    assert (
        preferred_strategy(ContentCategory.document, visual_bridge=False)
        is AssetStrategy.archive_image
    )
    assert (
        map_strategy(_intent(preferred_source_type="infographic"))
        is not AssetStrategy.generated_graphic
    )
    assert map_strategy(_intent(preferred_source_type="document")) is not AssetStrategy.document
    assert map_strategy(_intent(preferred_source_type="map")) is not AssetStrategy.map
    assert map_strategy(_intent(preferred_source_type="text_card")) is not AssetStrategy.text_card


def test_explicit_explainer_still_available() -> None:
    intent = _intent(preferred_source_type="infographic", explicit_explainer=True)
    assert map_strategy(intent) is AssetStrategy.generated_graphic
    intent = _intent(preferred_source_type="document", explicit_explainer=True)
    assert map_strategy(intent) is AssetStrategy.document
    intent = _intent(preferred_source_type="map", explicit_explainer=True)
    assert map_strategy(intent) is AssetStrategy.map
    intent = _intent(preferred_source_type="text_card", explicit_explainer=True)
    assert map_strategy(intent) is AssetStrategy.text_card


def test_statistics_dates_geography_legal_do_not_force_graphics() -> None:
    assert statistics_do_not_imply_chart("yüzde 80") is not AssetStrategy.generated_graphic
    assert dates_do_not_imply_document("30 Temmuz 2012") is not AssetStrategy.document
    assert geography_does_not_imply_map("Quebec Ontario ABD") is not AssetStrategy.map
    assert (
        legal_outcome_does_not_imply_court_graphic("Yüksek Mahkeme")
        is not AssetStrategy.generated_graphic
    )


def test_stock_preferred_before_ai_and_archive_when_evidence() -> None:
    scene = _scene(14, AssetStrategy.map, "Quebec dünya üretiminin yüzde 80.", "map")
    unit = _unit("au_0014", ["scene_0014"], AssetStrategy.map)
    plan = ScenePlan(project_id="p", scenes=[scene], total_duration=scene.end)
    asset = AssetPlan(
        project_id="p", scene_count=1, asset_unit_count=1, saved_generation_count=0, units=[unit]
    )
    stock = Path("/tmp/warehouse.mp4")
    report = plan_explainer_replacements(
        plan, asset, library={"maple_harvesting": [stock], "warehouse_barrels": [stock]}
    )
    assert report.bad_units[0].source_type == "existing_stock"
    court = _scene(52, AssetStrategy.document, "Yüksek Mahkeme 9.17 milyon.", "court")
    unit2 = _unit("au_0052", ["scene_0052"], AssetStrategy.document)
    plan2 = ScenePlan(project_id="p", scenes=[court], total_duration=court.end)
    asset2 = AssetPlan(
        project_id="p", scene_count=1, asset_unit_count=1, saved_generation_count=0, units=[unit2]
    )
    photo = Path("/tmp/scc.jpg")
    report2 = plan_explainer_replacements(
        plan2, asset2, library={"archive_evidence": [photo], "courthouse": [photo]}
    )
    assert report2.bad_units[0].source_type in {"archive", "reuse_photo", "existing_stock"}


def test_ai_still_fallback_and_no_named_portrait() -> None:
    scene = _scene(43, AssetStrategy.document, "Richard Vallières tutuklandı.", "named")
    unit = _unit("au_0043", ["scene_0043"], AssetStrategy.document)
    plan = ScenePlan(project_id="p", scenes=[scene], total_duration=scene.end)
    asset = AssetPlan(
        project_id="p", scene_count=1, asset_unit_count=1, saved_generation_count=0, units=[unit]
    )
    report = plan_explainer_replacements(plan, asset, library={})
    assert report.bad_units
    plan2, asset2 = apply_replacement_strategies(plan, asset, report)
    assert plan2.scenes[0].asset_strategy is not AssetStrategy.document
    assert "portrait" not in (plan2.scenes[0].generation.image_prompt or "").lower()
    assert fallback_strategy(scene) is not AssetStrategy.ai_image or True


def test_photo_sequence_asset_and_repetition() -> None:
    seq = PhotoSequenceAsset(stills=["a.jpg", "b.jpg"], concept_keys=["warehouse", "barrels"])
    assert len(seq.stills) == 2
    s1 = _scene(1, AssetStrategy.generated_graphic, "Depo fıçıları.", "barrels")
    s2 = _scene(2, AssetStrategy.generated_graphic, "Yine depo fıçıları.", "barrels")
    s3 = _scene(3, AssetStrategy.generated_graphic, "Polis soruşturması.", "police")
    c1 = concept_for_scene(s1, [])
    c2 = concept_for_scene(s2, [c1])
    c3 = concept_for_scene(s3, [c1, c2])
    assert c3 != c2 or c3 == "police_investigation"


def test_explainer_units_detected_and_explicit_skipped() -> None:
    scene = _scene(11, AssetStrategy.generated_graphic, "Federasyon 1966.", "chart")
    unit = _unit("au_0011", ["scene_0011"], AssetStrategy.generated_graphic)
    assert is_generated_explainer_unit(unit, scene)
    scene.metadata["explicit_explainer"] = True
    assert not is_generated_explainer_unit(unit, scene)


def test_narration_alignment_and_subtitles_not_in_replacement_plan() -> None:
    scene = _scene(4, AssetStrategy.document, "30 Temmuz 2012.", "date")
    unit = _unit("au_0004", ["scene_0004"], AssetStrategy.document)
    plan = ScenePlan(project_id="p", scenes=[scene], total_duration=scene.end)
    asset = AssetPlan(
        project_id="p", scene_count=1, asset_unit_count=1, saved_generation_count=0, units=[unit]
    )
    report = plan_explainer_replacements(plan, asset, library={})
    plan2, _asset2 = apply_replacement_strategies(plan, asset, report)
    assert plan2.scenes[0].narration == scene.narration
    assert plan2.scenes[0].start == scene.start
    assert plan2.scenes[0].end == scene.end
    assert plan2.scenes[0].subtitle == scene.subtitle
