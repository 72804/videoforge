from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from docprod.cli import app
from docprod.graphics.map import map_labels, use_story_geography
from docprod.models.enums import AssetStrategy, Mood, TransitionType, VisualEffect
from docprod.models.project import Project
from docprod.models.scene import GenerationSpec, Scene, ScenePlan
from docprod.pipeline.prepare_production import prepare_production
from docprod.storage.json_store import save_model
from docprod.storage.paths import ProjectPaths

runner = CliRunner()


def _scene(n: int, **kwargs: object) -> Scene:
    strategy = kwargs.get("strategy", AssetStrategy.generated_graphic)
    assert isinstance(strategy, AssetStrategy)
    prompt = "p" if strategy in {AssetStrategy.ai_image, AssetStrategy.ai_image_to_video} else None
    return Scene(
        id=f"scene_{n:04d}",
        start=float(n - 1) * 3,
        end=float(n) * 3,
        duration=3.0,
        narration=str(kwargs.get("narration") or "Depo fıçıları."),
        visual_intent=str(kwargs.get("subject") or "warehouse"),
        asset_strategy=strategy,
        effect=VisualEffect.none,
        transition=TransitionType.cut,
        mood=Mood.neutral,
        subtitle="x",
        generation=GenerationSpec(image_prompt=prompt),
        metadata={
            "visual_subject": str(kwargs.get("subject") or "warehouse"),
            "chapter": str(kwargs.get("chapter") or "HOOK"),
            "graphic_brief": str(kwargs.get("brief") or ""),
            "movement_need": "low",
            "image_prompt_seed": "warehouse barrels",
        },
    )


def _setup(tmp_path: Path, monkeypatch, scenes: list[Scene]) -> ProjectPaths:
    monkeypatch.setattr("docprod.storage.paths.default_projects_root", lambda: tmp_path)
    monkeypatch.setattr("docprod.cli.pathmod.default_projects_root", lambda: tmp_path)
    paths = ProjectPaths(tmp_path / "maple_heist_canary")
    paths.root.mkdir(parents=True)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    save_model(
        paths.project_json,
        Project(
            id="maple_heist_canary",
            title="Maple",
            language="tr",
            target_duration_seconds=420,
            created_at=now,
            updated_at=now,
        ),
    )
    plan = ScenePlan(project_id="maple_heist_canary", scenes=scenes, total_duration=scenes[-1].end)
    save_model(paths.scene_plan_json, plan)
    return paths


def test_prepare_local_only_and_cost_zero_network(tmp_path, monkeypatch) -> None:
    scenes = [
        _scene(
            1,
            strategy=AssetStrategy.map,
            narration="Quebec ve Kedgwick soruşturma konumları.",
            subject="map",
        ),
        _scene(
            2,
            strategy=AssetStrategy.ai_image_to_video,
            narration="Denetim.",
            subject="inventory barrel scale",
        ),
        _scene(
            3,
            strategy=AssetStrategy.ai_image_to_video,
            narration="Denetim devam.",
            subject="inventory barrel scale",
        ),
        _scene(
            4,
            strategy=AssetStrategy.document,
            narration="Mahkeme özeti.",
            subject="court summary",
        ),
    ]
    paths = _setup(tmp_path, monkeypatch, scenes)
    project = Project.model_validate_json(paths.project_json.read_text())
    plan = ScenePlan.model_validate_json(paths.scene_plan_json.read_text())
    called = {"n": 0}

    def boom(*_a, **_k):
        called["n"] += 1
        raise AssertionError("network")

    monkeypatch.setattr("docprod.research.openai_web.OpenAIResponsesProvider.create", boom)
    result = prepare_production(
        paths,
        project=project,
        plan=plan,
        enable_pexels=False,
        enable_commons=False,
        enable_local_graphics=True,
    )
    assert called["n"] == 0
    assert result.asset_plan.scene_count == 4
    assert result.asset_plan.saved_generation_count >= 1
    video_units = [u for u in result.asset_plan.units if u.status == "NEEDS_AI_VIDEO"]
    assert len(video_units) == 1
    assert len(video_units[0].scene_ids) == 2
    assert result.asset_plan.cost is not None
    assert result.asset_plan.cost.known_total == "price unresolved"
    labels = map_labels(plan.scenes[0])
    assert "güzergah" in labels["note"].casefold() or "güzergâh" in labels["note"].casefold()
    assert use_story_geography(plan.scenes[0])
    cost = runner.invoke(app, ["estimate-production-cost", "maple_heist_canary"])
    assert cost.exit_code == 0
    assert "price unresolved" in cost.stdout


def test_planner_demo_map_unchanged_for_station_story() -> None:
    scene = _scene(
        1,
        strategy=AssetStrategy.map,
        narration="Kuzey kapısına giden şematik rota.",
        subject="station",
    )
    assert not use_story_geography(scene)


def test_named_person_fallback_is_document_not_ai_portrait() -> None:
    from docprod.production.prompts import fallback_strategy

    scene = _scene(
        1,
        strategy=AssetStrategy.archive_image,
        narration="Michel Gauvreau envanter kaydı.",
        subject="Michel Gauvreau",
    )
    assert fallback_strategy(scene) is AssetStrategy.document


def test_inspect_production_plan_cli(tmp_path, monkeypatch) -> None:
    scenes = [
        _scene(1, strategy=AssetStrategy.document, narration="Mahkeme.", subject="court"),
    ]
    paths = _setup(tmp_path, monkeypatch, scenes)
    project = Project.model_validate_json(paths.project_json.read_text())
    plan = ScenePlan.model_validate_json(paths.scene_plan_json.read_text())
    prepare_production(
        paths,
        project=project,
        plan=plan,
        enable_pexels=False,
        enable_commons=False,
        enable_local_graphics=True,
    )
    inspect = runner.invoke(app, ["inspect-production-plan", "maple_heist_canary"])
    assert inspect.exit_code == 0
    assert "READY_LOCAL" in inspect.stdout
