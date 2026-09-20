from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from PIL import Image
from pydantic import SecretStr
from tests.providers.test_openai_image import FakeClient, FakeImages

from docprod.config import Settings
from docprod.drama.planner import compile_drama_scene_plan
from docprod.drama.story import build_birko_script
from docprod.pipeline.migrate_character_stills import (
    build_still_migration_jobs,
    execute_still_migration,
    i2v_start_image_path,
    preflight_still_migration,
)
from docprod.providers.image_config import ImageGenerationConfig
from docprod.providers.openai_image import (
    OPENAI_IMAGE_EDIT_MAX_REFERENCE_FILES,
    OpenAIImageProvider,
)
from docprod.providers.paid_cache import PaidArtifactCache
from docprod.providers.pricing import (
    BIRKO_DRAMA_IMAGE_ATTRIBUTABLE_USD,
    BIRKO_DRAMA_IMAGE_PAID_CALLS,
    IMAGE_MIGRATION_HARD_CAP_USD,
    MAPLE_7_IMAGE_BATCH_TOTAL_USD,
    V2_VIDEO_TOTAL_USD,
    birko_implied_image_unit_usd,
    estimated_image_migration_usd,
)
from docprod.quality.character_refs import (
    IMAGE_COST_ESTIMATE_USD,
    bind_scene_identity_references,
    import_character_images,
    migration_summary,
    plan_character_migration,
)
from docprod.quality.enums import CostConfidence
from docprod.render.still import resolve_generated_still
from docprod.storage.paths import ProjectPaths, ensure_project_layout


def _jpeg(
    path: Path,
    *,
    size: tuple[int, int] = (640, 800),
    color: tuple[int, int, int] = (20, 40, 60),
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path, "JPEG")
    return path


def _settings() -> Settings:
    return Settings(
        allow_paid_apis=True,
        openai_api_key=SecretStr("test-not-a-real-key"),
        log_level="INFO",
    )


def _ready_project(tmp_path: Path) -> tuple[ProjectPaths, object]:
    paths = ProjectPaths(tmp_path / "birko_kemal_drama_canary")
    ensure_project_layout(paths)
    for cid, color in (("birko", (10, 0, 0)), ("kemal", (0, 10, 0)), ("muge", (0, 0, 10))):
        src = tmp_path / f"{cid}_front.jpg"
        _jpeg(src, color=color)
        import_character_images(paths, cid, [src])
        _jpeg(paths.generated_character_refs_dir() / f"ref_{cid}.jpg", color=(1, 1, 1))
    script = build_birko_script(project_id="birko_kemal_drama_canary")
    plan = compile_drama_scene_plan(script)
    for scene in plan.scenes:
        chars = (scene.metadata or {}).get("characters") or []
        if not chars:
            continue
        _jpeg(paths.scene_image_path(scene.id), size=(1536, 864), color=(80, 80, 80))
    return paths, plan


def test_maple_batch_is_not_a_per_image_price() -> None:
    assert MAPLE_7_IMAGE_BATCH_TOTAL_USD == pytest.approx(0.06698)
    assert IMAGE_COST_ESTIMATE_USD is None
    assert BIRKO_DRAMA_IMAGE_PAID_CALLS == 24
    assert BIRKO_DRAMA_IMAGE_ATTRIBUTABLE_USD == pytest.approx(0.371)
    wrong = 18 * MAPLE_7_IMAGE_BATCH_TOTAL_USD
    assert estimated_image_migration_usd(18) != pytest.approx(wrong)
    assert estimated_image_migration_usd(18) == pytest.approx(0.2782)
    assert birko_implied_image_unit_usd() == pytest.approx(0.015458, rel=1e-3)


def test_three_character_bind_never_drops(tmp_path: Path) -> None:
    paths, _plan = _ready_project(tmp_path)
    bound = bind_scene_identity_references(
        paths, ["birko", "muge", "kemal"], provider="openai", task="image"
    )
    assert len(bound) == 3
    ids = [cid for cid, _path, _ver in bound]
    assert ids == ["birko", "muge", "kemal"]
    assert all(path.is_file() for _cid, path, _ver in bound)
    assert OPENAI_IMAGE_EDIT_MAX_REFERENCE_FILES >= 3


def test_eighteen_scene_manifest_and_b15_refs(tmp_path: Path) -> None:
    paths, plan = _ready_project(tmp_path)
    jobs = build_still_migration_jobs(paths, plan, settings=_settings())
    assert len(jobs) == 18
    rows = [row for row in plan_character_migration(paths, plan) if row.regeneration_required]
    assert len(rows) == 18
    summary = migration_summary(rows)
    assert summary["cost_confidence"] == CostConfidence.ESTIMATED.value
    assert "BATCH total" in summary["cost_basis"]
    assert summary["hard_cap_usd"] == pytest.approx(IMAGE_MIGRATION_HARD_CAP_USD)
    b15 = next(job for job in jobs if job.beat_id == "b15")
    assert b15.scene_id == "scene_0020"
    assert b15.characters == ["birko", "muge", "kemal"]
    assert b15.reference_count == 3
    dual = [job for job in jobs if job.reference_count == 2]
    assert {job.beat_id for job in dual} >= {"b02", "b15b"}
    pre = preflight_still_migration(paths, plan, settings=_settings())
    assert pre.b15_all_three_refs is True
    assert pre.calls == 18
    assert pre.video_usd == pytest.approx(V2_VIDEO_TOTAL_USD)
    assert pre.hard_cap_usd == pytest.approx(1.0)
    assert pre.estimated_usd == pytest.approx(estimated_image_migration_usd(18))
    assert "identity" in b15.prompt.casefold()
    assert "Birko" in b15.prompt and "Kemal" in b15.prompt and "Müge" in b15.prompt


def test_cache_hash_includes_custom_refs_and_versions(tmp_path: Path) -> None:
    paths, plan = _ready_project(tmp_path)
    first = {job.scene_id: job.request_hash for job in build_still_migration_jobs(paths, plan)}
    incoming = tmp_path / "birko_new.jpg"
    _jpeg(incoming, color=(99, 1, 2))
    import_character_images(paths, "birko", [incoming])
    second = {job.scene_id: job.request_hash for job in build_still_migration_jobs(paths, plan)}
    changed = [sid for sid, digest in first.items() if digest != second[sid]]
    assert changed
    unchanged = [sid for sid, digest in first.items() if digest == second[sid]]
    assert unchanged


def test_v1_never_overwritten_resume_and_cap(tmp_path: Path) -> None:
    paths, plan = _ready_project(tmp_path)
    v1 = paths.scene_image_path("scene_0020")
    before = v1.read_bytes()
    images = FakeImages(usage={"input_tokens": 80, "output_tokens": 40})
    provider = OpenAIImageProvider(
        settings=_settings(),
        config=ImageGenerationConfig.from_settings(_settings()),
        client=FakeClient(images),
    )
    cache = PaidArtifactCache(tmp_path / "paid")
    dry = execute_still_migration(paths, plan, confirm_paid=False, settings=_settings())
    assert dry["paid_calls"] == 0
    assert dry["executed"] is False
    first = execute_still_migration(
        paths,
        plan,
        confirm_paid=True,
        settings=_settings(),
        provider=provider,
        cache=cache,
    )
    assert first["paid_calls"] == 18
    assert v1.read_bytes() == before
    custom = paths.custom_v2_scene_image("scene_0020")
    assert custom.is_file()
    assert custom.resolve() != v1.resolve()
    second = execute_still_migration(
        paths,
        plan,
        confirm_paid=True,
        settings=_settings(),
        provider=provider,
        cache=cache,
    )
    assert second["paid_calls"] == 0
    shutil.rmtree(paths.custom_v2_dir())
    with pytest.raises(RuntimeError, match="cap"):
        execute_still_migration(
            paths,
            plan,
            confirm_paid=True,
            settings=_settings(),
            provider=provider,
            cache=PaidArtifactCache(tmp_path / "other-cache"),
            hard_cap_usd=0.01,
        )


def test_i2v_uses_migrated_still(tmp_path: Path) -> None:
    paths, plan = _ready_project(tmp_path)
    scene = next(s for s in plan.scenes if (s.metadata or {}).get("beat_id") == "b15")
    with pytest.raises(RuntimeError, match="custom_v2"):
        i2v_start_image_path(paths, scene)
    custom = paths.custom_v2_scene_image(scene.id)
    _jpeg(custom, size=(1536, 864), color=(3, 4, 5))
    assert i2v_start_image_path(paths, scene) == custom
    resolved = resolve_generated_still(paths, scene.id)
    assert resolved is not None
    assert resolved[0] == custom
