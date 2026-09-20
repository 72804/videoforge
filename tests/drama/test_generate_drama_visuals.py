from __future__ import annotations

from pathlib import Path

from pydantic import SecretStr
from tests.providers.test_openai_image import FakeClient, FakeImages

from docprod.config import Settings
from docprod.drama.planner import compile_drama_scene_plan
from docprod.drama.story import CHARACTER_REF_PLAN, build_birko_script
from docprod.pipeline.generate_drama_visuals import (
    execute_generate_drama_visuals,
    plan_drama_visual_jobs,
)
from docprod.providers.image_config import ImageGenerationConfig
from docprod.providers.openai_image import OpenAIImageProvider
from docprod.providers.paid_cache import PaidArtifactCache
from docprod.storage.paths import ProjectPaths, ensure_project_layout


def _settings() -> Settings:
    return Settings(
        allow_paid_apis=True,
        openai_api_key=SecretStr("test-not-a-real-key"),
        log_level="INFO",
    )


def test_plan_has_3_refs_and_21_timeline() -> None:
    paths = ProjectPaths(root=Path("/tmp/unused-drama-plan"))
    script = build_birko_script(project_id="tiny_drama")
    plan = compile_drama_scene_plan(script)
    jobs, cfg = plan_drama_visual_jobs(paths, plan)
    assert cfg.model == "gpt-image-2.5-flare"
    assert cfg.quality == "medium"
    assert cfg.size == "1536x864"
    assert sum(1 for job in jobs if job.kind == "character_ref") == 3
    assert sum(1 for job in jobs if job.kind == "timeline") == 21
    assert {item["id"] for item in CHARACTER_REF_PLAN} == {"ref_kemal", "ref_birko", "ref_muge"}


def test_drama_visuals_generate_then_cache(tmp_path: Path) -> None:
    paths = ProjectPaths(root=tmp_path / "birko_kemal_drama_canary")
    ensure_project_layout(paths)
    script = build_birko_script(project_id="birko_kemal_drama_canary")
    plan = compile_drama_scene_plan(script)
    images = FakeImages()
    cfg = ImageGenerationConfig.from_settings(_settings())
    provider = OpenAIImageProvider(settings=_settings(), config=cfg, client=FakeClient(images))
    first = execute_generate_drama_visuals(
        paths,
        plan=plan,
        confirm_paid=True,
        settings=_settings(),
        provider=provider,
        cache=PaidArtifactCache(tmp_path / "paid"),
    )
    assert first.ref_count == 3
    assert first.timeline_count == 21
    assert first.paid_calls == 24
    assert first.failed == []
    assert (paths.visuals_dir / "character_refs" / "ref_kemal.jpg").is_file()
    second = execute_generate_drama_visuals(
        paths,
        plan=plan,
        confirm_paid=False,
        settings=_settings(),
        provider=provider,
        cache=PaidArtifactCache(tmp_path / "paid"),
    )
    assert second.paid_calls == 0
    assert second.cache_hits == 24
    assert len(images.calls) == 24
