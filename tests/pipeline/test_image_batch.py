from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.providers.test_openai_image import JPEG_BYTES, FakeClient, FakeImages, _settings

from docprod.exceptions import MaxPaidRequestsExceededError
from docprod.models.enums import AssetStrategy, Mood, TransitionType, VisualEffect
from docprod.models.scene import GenerationSpec, Scene, ScenePlan
from docprod.pipeline.generate_image_stage import archive_active_still, execute_generate_image
from docprod.pipeline.generate_images_batch import execute_generate_images, plan_image_batch
from docprod.providers.image_config import GeneratedImageManifest
from docprod.providers.image_review import load_review, set_review_state
from docprod.providers.openai_image import OpenAIImageProvider
from docprod.storage.hashing import file_sha256
from docprod.storage.json_store import save_model
from docprod.storage.paths import ProjectPaths


def _scene(
    scene_id: str,
    narration: str,
    strategy: AssetStrategy,
    *,
    start: float = 0.0,
    category: str = "person",
) -> Scene:
    return Scene(
        id=scene_id,
        start=start,
        end=start + 1.0,
        duration=1.0,
        narration=narration,
        visual_intent=narration,
        asset_strategy=strategy,
        effect=VisualEffect.slow_push_in,
        transition=TransitionType.cut,
        mood=Mood.neutral,
        subtitle=narration,
        generation=GenerationSpec(image_prompt=narration)
        if strategy in {AssetStrategy.ai_image, AssetStrategy.ai_image_to_video}
        else GenerationSpec(),
        metadata={"primary_category": category},
    )


def _plan(*scenes: Scene) -> ScenePlan:
    items = list(scenes)
    return ScenePlan(
        project_id="planner_demo",
        scenes=items,
        total_duration=items[-1].end if items else 0.0,
    )


def _seed_image(paths: ProjectPaths, scene_id: str, request_hash: str = "old-hash") -> None:
    image = paths.scene_image_path(scene_id)
    image.parent.mkdir(parents=True, exist_ok=True)
    image.write_bytes(JPEG_BYTES)
    save_model(
        paths.scene_image_meta(scene_id),
        GeneratedImageManifest(
            provider="openai",
            model="gpt-image-2.5-flare",
            scene_id=scene_id,
            prompt="old prompt",
            size="1536x864",
            quality="medium",
            output_format="jpeg",
            source_scene_hash="x",
            request_hash=request_hash,
            output_path=f"artifacts/visuals/{scene_id}/image.jpg",
            output_sha256=file_sha256(image),
            generation_status="success",
        ),
    )


def test_approved_asset_skipped_without_provider_call(tmp_path: Path) -> None:
    paths = ProjectPaths(root=tmp_path / "proj")
    plan = _plan(_scene("scene_0003", "Three dogs wait.", AssetStrategy.ai_image))
    _seed_image(paths, "scene_0003")
    digest = file_sha256(paths.scene_image_path("scene_0003"))
    set_review_state(paths, "scene_0003", "approved", artifact_sha256=digest)
    images = FakeImages()
    provider = OpenAIImageProvider(settings=_settings(), client=FakeClient(images))
    result = execute_generate_image(
        paths,
        plan=plan,
        scene_id="scene_0003",
        confirm_paid=False,
        settings=_settings(),
        provider=provider,
    )
    assert result.cache_hit is True
    assert result.note == "approved"
    assert images.calls == []


def test_force_on_exact_scene_regenerates(tmp_path: Path) -> None:
    paths = ProjectPaths(root=tmp_path / "proj")
    plan = _plan(_scene("scene_0003", "Three dogs wait.", AssetStrategy.ai_image))
    _seed_image(paths, "scene_0003")
    digest = file_sha256(paths.scene_image_path("scene_0003"))
    set_review_state(paths, "scene_0003", "approved", artifact_sha256=digest)
    images = FakeImages()
    provider = OpenAIImageProvider(settings=_settings(), client=FakeClient(images))
    execute_generate_image(
        paths,
        plan=plan,
        scene_id="scene_0003",
        confirm_paid=True,
        force=True,
        settings=_settings(),
        provider=provider,
    )
    assert len(images.calls) == 1


def test_batch_discovers_only_image_strategies(tmp_path: Path) -> None:
    paths = ProjectPaths(root=tmp_path / "proj")
    plan = _plan(
        _scene(
            "scene_0001",
            "Station at dusk.",
            AssetStrategy.stock_video,
            start=0.0,
            category="location_establishing",
        ),
        _scene("scene_0002", "Koyu paltolu bir adam indi.", AssetStrategy.ai_image, start=1.0),
        _scene("scene_0003", "A map.", AssetStrategy.map, start=2.0, category="map"),
        _scene("scene_0004", "Adam yürüdü.", AssetStrategy.ai_image_to_video, start=3.0),
        _scene("scene_0005", "A report.", AssetStrategy.document, start=4.0, category="document"),
    )
    jobs, _cfg = plan_image_batch(paths, plan, settings=_settings())
    assert [job.scene.id for job in jobs] == ["scene_0002", "scene_0004"]
    assert all(job.action == "GENERATE" for job in jobs)


def test_max_paid_requests_aborts_before_calls(tmp_path: Path) -> None:
    paths = ProjectPaths(root=tmp_path / "proj")
    plan = _plan(
        _scene("scene_0002", "Koyu paltolu bir adam indi.", AssetStrategy.ai_image, start=0.0),
        _scene("scene_0004", "Adam yürüdü.", AssetStrategy.ai_image_to_video, start=1.0),
    )
    images = FakeImages()
    provider = OpenAIImageProvider(settings=_settings(), client=FakeClient(images))
    with pytest.raises(MaxPaidRequestsExceededError, match="Aborting before any API call"):
        execute_generate_images(
            paths,
            plan=plan,
            confirm_paid=True,
            max_paid_requests=1,
            settings=_settings(),
            provider=provider,
        )
    assert images.calls == []


def test_cached_image_not_counted_as_paid(tmp_path: Path) -> None:
    paths = ProjectPaths(root=tmp_path / "proj")
    plan = _plan(
        _scene("scene_0002", "Three dogs wait.", AssetStrategy.ai_image, category="generic")
    )
    images = FakeImages()
    provider = OpenAIImageProvider(settings=_settings(), client=FakeClient(images))
    execute_generate_image(
        paths,
        plan=plan,
        scene_id="scene_0002",
        confirm_paid=True,
        settings=_settings(),
        provider=provider,
    )
    manifest = execute_generate_images(
        paths,
        plan=plan,
        confirm_paid=True,
        max_paid_requests=0,
        settings=_settings(),
        provider=provider,
    )
    assert manifest.planned_paid_requests == 0
    assert manifest.skipped == 1
    assert manifest.generated == 0
    assert len(images.calls) == 1
    dumped = paths.image_batch_manifest().read_text(encoding="utf-8").lower()
    assert "api_key" not in dumped
    assert "test-not-a-real-key" not in dumped
    assert "authorization" not in dumped
    payload = json.loads(paths.image_batch_manifest().read_text(encoding="utf-8"))
    assert payload["scenes"][0]["status"] == "skipped"


def test_max_paid_cap_of_two_aborts_before_calls(tmp_path: Path) -> None:
    paths = ProjectPaths(root=tmp_path / "proj")
    plan = _plan(
        _scene("scene_0006", "Durdu.", AssetStrategy.ai_image, start=0.0),
        _scene("scene_0013", "Adam kaçan birini kovaladı.", AssetStrategy.ai_image, start=1.0),
        _scene("scene_0014", "Adam durdu tekrar.", AssetStrategy.ai_image, start=2.0),
    )
    images = FakeImages()
    provider = OpenAIImageProvider(settings=_settings(), client=FakeClient(images))
    with pytest.raises(MaxPaidRequestsExceededError, match="Aborting before any API call"):
        execute_generate_images(
            paths,
            plan=plan,
            confirm_paid=True,
            max_paid_requests=2,
            settings=_settings(),
            provider=provider,
        )
    assert images.calls == []


def test_only_scene_ids_limits_paid_plan(tmp_path: Path) -> None:
    paths = ProjectPaths(root=tmp_path / "proj")
    plan = _plan(
        _scene("scene_0006", "Durdu.", AssetStrategy.ai_image, start=0.0),
        _scene("scene_0010", "Polis memurları perona girdi.", AssetStrategy.ai_image, start=1.0),
        _scene("scene_0013", "Adam kaçan birini kovaladı.", AssetStrategy.ai_image, start=2.0),
    )
    jobs, _cfg = plan_image_batch(
        paths,
        plan,
        settings=_settings(),
        only_scene_ids=("scene_0006", "scene_0013"),
        force_scene_ids=("scene_0006", "scene_0013"),
    )
    assert [job.scene.id for job in jobs] == ["scene_0006", "scene_0013"]


def test_regeneration_preserves_history_and_review(tmp_path: Path) -> None:
    paths = ProjectPaths(root=tmp_path / "proj")
    plan = _plan(_scene("scene_0006", "Durdu.", AssetStrategy.ai_image))
    _seed_image(paths, "scene_0006")
    old_digest = file_sha256(paths.scene_image_path("scene_0006"))
    set_review_state(paths, "scene_0006", "generated", artifact_sha256=old_digest)
    archived = archive_active_still(paths, "scene_0006", archived_as="rejected")
    assert archived is not None
    assert archived is not None and archived.is_file()
    from docprod.providers.image_review import ImageReviewRecord
    from docprod.storage.json_store import load_model

    record = load_model(
        paths.scene_image_history_dir("scene_0006") / f"{old_digest}.review.json",
        ImageReviewRecord,
    )
    assert record.review_state == "rejected"
    images = FakeImages()
    provider = OpenAIImageProvider(settings=_settings(), client=FakeClient(images))
    execute_generate_image(
        paths,
        plan=plan,
        scene_id="scene_0006",
        confirm_paid=True,
        force=True,
        archive_as="superseded",
        settings=_settings(),
        provider=provider,
    )
    assert archived.is_file()
    assert archived.read_bytes() == JPEG_BYTES
    active = load_review(paths, "scene_0006")
    assert active is not None
    assert active.review_state == "generated"
    history_meta = paths.scene_image_history_dir("scene_0006") / f"{old_digest}.meta.json"
    assert history_meta.is_file()

