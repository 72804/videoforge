from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from docprod.models.enums import AssetStrategy, Mood, TransitionType, VisualEffect
from docprod.models.project import Project
from docprod.models.scene import GenerationSpec, Scene, ScenePlan
from docprod.pipeline.improve_visual_diversity import (
    DiversityLiveStats,
    apply_diversity_item,
    plan_diversity_replacements,
)
from docprod.planning.semantic_compiler import map_strategy
from docprod.planning.semantic_models import SemanticSceneIntent
from docprod.planning.visual_diversity import (
    DiversityItem,
    SourceUse,
    court_rejects_warehouse_when_court_exists,
    detect_repetition,
    is_intentional_continuity,
    police_family_for_narration,
    supreme_court_archive_preferred,
    visual_need,
)
from docprod.planning.visual_policy import EXPLAINER_STRATEGIES
from docprod.production import AssetPlan, AssetUnit, PhotoSequenceAsset
from docprod.render.ffmpeg import probe_media, run_ffmpeg
from docprod.render.models import TINY_TEST_PROFILE
from docprod.render.renderer import render_preview
from docprod.storage.paths import ProjectPaths
from tests.render.helpers import mini_plan


def _scene(
    n: int,
    narration: str,
    *,
    start: float = 0.0,
    duration: float = 6.0,
    strategy: AssetStrategy = AssetStrategy.stock_video,
) -> Scene:
    return Scene(
        id=f"scene_{n:04d}",
        start=start,
        end=start + duration,
        duration=duration,
        narration=narration,
        visual_intent=narration,
        asset_strategy=strategy,
        effect=VisualEffect.slow_push_in,
        transition=TransitionType.cut,
        mood=Mood.neutral,
        subtitle=narration,
        generation=GenerationSpec(),
        metadata={"visual_subject": narration},
    )


def _unit(uid: str, scenes: list[str], extra: dict | None = None) -> AssetUnit:
    return AssetUnit(
        asset_unit_id=uid,
        scene_ids=scenes,
        source_strategy=AssetStrategy.stock_video,
        continuous_duration=6.0,
        visual_concept="x",
        status="READY_STOCK",
        extra=extra or {},
    )


def _write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def test_repetition_detector_and_continuity_exemption() -> None:
    uses = [
        SourceUse("a", ["scene_0001"], 0.0, 6.0, "srcA", "/a", "stock_video", "court", "x"),
        SourceUse("b", ["scene_0002"], 10.0, 6.0, "srcA", "/a", "stock_video", "court", "x"),
        SourceUse(
            "c", ["scene_0003"], 20.0, 6.0, "srcA", "/a", "stock_video", "warehouse_barrels", "x"
        ),
        SourceUse("d", ["scene_0004"], 40.0, 6.0, "srcA", "/a", "stock_video", "court", "x"),
    ]
    warnings = detect_repetition(uses)
    kinds = {item.kind for item in warnings}
    assert "UNWANTED_REPETITION" in kinds
    assert "NEARBY_REUSE" in kinds
    assert "SEMANTIC_MISMATCH_REUSE" in kinds
    exempt = [
        SourceUse(
            "a",
            ["scene_0001"],
            0.0,
            6.0,
            "srcB",
            "/b",
            "stock_video",
            "court",
            "x",
            exempt=True,
        ),
        SourceUse(
            "b",
            ["scene_0002"],
            5.0,
            6.0,
            "srcB",
            "/b",
            "stock_video",
            "court",
            "x",
            exempt=True,
        ),
        SourceUse(
            "c",
            ["scene_0003"],
            10.0,
            6.0,
            "srcB",
            "/b",
            "stock_video",
            "court",
            "x",
            exempt=True,
        ),
        SourceUse(
            "d",
            ["scene_0004"],
            15.0,
            6.0,
            "srcB",
            "/b",
            "stock_video",
            "court",
            "x",
            exempt=True,
        ),
    ]
    assert detect_repetition(exempt) == []
    unit = _unit("au_0001", ["scene_0001"], extra={"establishing_motif": True})
    assert is_intentional_continuity(unit)


def test_police_family_diversification_and_court_warehouse() -> None:
    assert (
        police_family_for_narration("federasyon polise başvurdu ve belgeler incelendi")
        == "investigators_files"
    )
    assert police_family_for_narration("sevkiyat kayıtlarını gözden geçirdi") == (
        "investigators_files"
    )
    assert (
        police_family_for_narration("gösterişli bir polis takibi değil yıllık envanter")
        is None
    )
    assert visual_need(_scene(55, "Kanada Yüksek Mahkemesi tazminatı onayladı")) == "scc"
    assert court_rejects_warehouse_when_court_exists(
        "jüri suçlu buldu ve hapis cezası verdi", "warehouse_barrels", True
    )
    assert supreme_court_archive_preferred("Yüksek Mahkeme kararı", True)


def test_explainer_graphics_stay_disabled() -> None:
    payload = {
        "intent_id": "I001",
        "chapter": "HOOK",
        "narration_span": "kelime",
        "narration_start_word": 0,
        "narration_end_word": 10,
        "visual_subject": "maple",
        "preferred_source_type": "infographic",
        "movement_need": "low",
        "historical_specificity": "generic",
    }
    intent = SemanticSceneIntent.model_validate(payload)
    assert map_strategy(intent) not in EXPLAINER_STRATEGIES
    intent = SemanticSceneIntent.model_validate({**payload, "preferred_source_type": "document"})
    assert map_strategy(intent) is not AssetStrategy.document
    intent = SemanticSceneIntent.model_validate({**payload, "preferred_source_type": "map"})
    assert map_strategy(intent) is not AssetStrategy.map


def test_plan_flags_police_duplicates_and_court_mismatch(tmp_path: Path) -> None:
    paths = ProjectPaths(root=tmp_path / "proj")
    clip = b"POLICECLIP" * 80
    warehouse = b"WAREHOUSEX" * 80
    scenes = []
    units = []
    # 3 police beats sharing one file within 60s
    narrations = [
        "federasyon polise başvurdu",
        "soruşturma kayıtlarını gözden geçirdi",
        "2012 de polis Kedgwick te operasyon yaptı",
    ]
    for index, text in enumerate(narrations, start=1):
        scene = _scene(index, text, start=float(index * 10))
        scenes.append(scene)
        dest = paths.stock_source_mp4(scene.id)
        _write_bytes(dest, clip)
        units.append(_unit(f"au_{index:04d}", [scene.id]))
    court = _scene(4, "jüri dört sanığı suçlu buldu hapis cezası", start=80.0)
    scenes.append(court)
    _write_bytes(paths.stock_source_mp4(court.id), warehouse)
    _write_bytes(paths.stock_source_meta(court.id), b'{"query": "steel barrels warehouse"}')
    units.append(_unit("au_0004", [court.id]))
    plan = ScenePlan(project_id="p", scenes=scenes, total_duration=86.0)
    asset = AssetPlan(
        project_id="p", scene_count=4, asset_unit_count=4, saved_generation_count=0, units=units
    )
    report = plan_diversity_replacements(paths, plan, asset)
    assert report.police_duplicate_max >= 3
    assert report.court_mismatch >= 1
    reasons = {item.reason for item in report.items}
    assert "police_source_duplicated" in reasons
    assert "court_warehouse_mismatch" in reasons
    assert report.paid_api_calls == 0


def _write_mp4(path: Path, *, color: str = "green") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            f"color=c={color}:s=1280x720:d=8",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ]
    )


def test_execute_uses_existing_stock_without_paid_apis(tmp_path: Path) -> None:
    paths = ProjectPaths(root=tmp_path / "proj")
    scene = _scene(1, "jüri hapis cezası verdi", start=0.0)
    _write_mp4(paths.stock_source_mp4("scene_0001"), color="red")
    _write_mp4(paths.stock_source_mp4("scene_0009"), color="blue")
    paths.stock_source_meta("scene_0009").write_text(
        '{"query": "courthouse exterior columns", "provider_video_id": "9"}',
        encoding="utf-8",
    )
    # dummy mp4 for bind_stock_clip probe — skip execute bind by applying existing path only
    plan = ScenePlan(project_id="p", scenes=[scene], total_duration=6.0)
    unit = _unit("au_0001", ["scene_0001"])
    asset = AssetPlan(
        project_id="p", scene_count=1, asset_unit_count=1, saved_generation_count=0, units=[unit]
    )
    item = DiversityItem(
        unit_id="au_0001",
        scene_ids=["scene_0001"],
        reason="court_warehouse_mismatch",
        family="court",
        action="existing_stock",
        old_source_id="x",
        narration_snippet=scene.narration,
    )
    stats = DiversityLiveStats()
    apply_diversity_item(
        paths,
        project=Project(
            id="tiny",
            title="t",
            language="tr",
            target_duration_seconds=6,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            updated_at=datetime(2026, 1, 1, tzinfo=UTC),
            random_seed=1,
        ),
        plan=plan,
        asset_plan=asset,
        item=item,
        used_ids=set(),
        library={"court": [paths.stock_source_mp4("scene_0009")]},
        session_uses=Counter(),
        stats=stats,
        pexels=False,
        commons_on=False,
    )
    assert stats.paid_api_calls == 0
    assert asset.units[0].source_strategy not in EXPLAINER_STRATEGIES
    assert asset.units[0].source_strategy is not AssetStrategy.document
    assert asset.units[0].source_strategy is not AssetStrategy.map


def test_photo_sequence_runtime_and_cache(tmp_path: Path) -> None:
    paths = ProjectPaths(root=tmp_path / "proj")
    paths.preview_segments_dir.mkdir(parents=True, exist_ok=True)
    scene = _scene(
        8,
        "Yüksek Mahkeme kararı",
        start=0.0,
        duration=0.8,
        strategy=AssetStrategy.archive_image,
    )
    still_a = paths.archive_source_path("au_0008", ".jpg")
    still_b = still_a.parent / "seq_1.jpg"
    for path, color in ((still_a, "red"), (still_b, "blue")):
        path.parent.mkdir(parents=True, exist_ok=True)
        run_ffmpeg(
            ["-f", "lavfi", "-i", f"color=c={color}:s=320x180", "-frames:v", "1", str(path)]
        )
    scene = scene.model_copy(
        update={
            "metadata": {
                "photo_sequence": [still_a.as_posix(), still_b.as_posix()],
                "photo_sequence_split": "1",
                "photo_sequence_index": 0,
            }
        }
    )
    project = Project(
        id="tiny",
        title="t",
        language="tr",
        target_duration_seconds=1,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        random_seed=1,
    )
    first = render_preview(
        paths,
        project=project,
        plan=mini_plan(scene),
        profile=TINY_TEST_PROFILE,
        workers=1,
        use_cache=True,
    )
    assert "photo-sequence" in first.manifest.segments[0].ffmpeg_command_summary
    probe = probe_media(paths.preview_segments_dir / "scene_0008.mp4")
    assert probe.width == TINY_TEST_PROFILE.width
    second = render_preview(
        paths,
        project=project,
        plan=mini_plan(scene),
        profile=TINY_TEST_PROFILE,
        workers=1,
        use_cache=True,
    )
    assert second.cache_hits == 1
    seq = PhotoSequenceAsset(stills=[still_a.as_posix(), still_b.as_posix()], concept_keys=["scc"])
    assert len(seq.stills) == 2


def test_narration_timing_fields_untouched_by_plan(tmp_path: Path) -> None:
    paths = ProjectPaths(root=tmp_path / "proj")
    scene = _scene(1, "federasyon polise başvurdu", start=3.5, duration=6.2)
    _write_bytes(paths.stock_source_mp4(scene.id), b"AAAA" * 40)
    plan = ScenePlan(project_id="p", scenes=[scene], total_duration=9.7)
    asset = AssetPlan(
        project_id="p",
        scene_count=1,
        asset_unit_count=1,
        saved_generation_count=0,
        units=[_unit("au_0001", [scene.id])],
    )
    before = (scene.narration, scene.start, scene.end, scene.subtitle)
    plan_diversity_replacements(paths, plan, asset)
    after = plan.scenes[0]
    assert after.narration == before[0]
    assert after.start == before[1]
    assert after.end == before[2]
    assert after.subtitle == before[3]
