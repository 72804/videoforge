from __future__ import annotations

from pathlib import Path

from docprod.demo import build_demo_scene_plan
from docprod.models.project import Project
from docprod.models.scene import SCENE_ID_PATTERN
from docprod.product.demo import DEMO_PROMPT, DEMO_TELEGRAM_USER_ID, run_telegram_product_demo
from docprod.product.enums import DurationMode, JobStatus
from docprod.quality.locked import BIRKO_V2_BALANCED_ROUTES, V2_HARD_CAP_USD, VEO_LITE


def test_telegram_product_demo_is_offline(tmp_path: Path) -> None:
    result = run_telegram_product_demo(root=tmp_path / "blobs")
    assert result["paid_api_calls"] == 0
    assert result["telegram_network"] is False
    assert result["telegram_user_id"] == DEMO_TELEGRAM_USER_ID
    svc = result["service"]
    project = svc.repo.projects[result["project_id"]]
    assert project.prompt == DEMO_PROMPT
    assert project.duration_mode is DurationMode.AUTO
    assert len(result["character_ids"]) == 2
    assert len(result["scene_ids"]) == 3
    job = svc.repo.jobs[result["job_id"]]
    assert job.status is JobStatus.COMPLETED
    assert job.authorized is True
    assert "project_ready" in result["outbox"]
    summaries = svc.scene_summaries(result["user_id"], result["project_id"])
    assert summaries[0].can_regenerate is True


def test_birko_locked_routes_untouched() -> None:
    assert set(BIRKO_V2_BALANCED_ROUTES) == {
        "b06",
        "b07",
        "b09",
        "b13",
        "b14",
        "b15",
        "b17",
        "b18",
    }
    assert all(model == VEO_LITE for model in BIRKO_V2_BALANCED_ROUTES.values())
    assert V2_HARD_CAP_USD == 3.20
    root = Path("projects/birko_kemal_drama_canary")
    v1 = root / "artifacts/render/final/birko_kemal_drama_v1.mp4"
    v2 = root / "artifacts/render/final/birko_kemal_drama_v2.mp4"
    if v1.is_file():
        assert v1.stat().st_size > 0
    if v2.is_file():
        assert v2.stat().st_size > 0
        assert v1.is_file()


def test_maple_engine_scene_contract_intact() -> None:
    plan = build_demo_scene_plan("demo", 1)
    assert plan.scenes
    assert all(SCENE_ID_PATTERN.fullmatch(scene.id) for scene in plan.scenes)
    maple = Path("projects/maple_heist_canary")
    if (maple / "project.json").is_file():
        from docprod.storage.json_store import load_model

        project = load_model(maple / "project.json", Project)
        assert project.id == "maple_heist_canary"
        assert project.target_duration_seconds > 0
