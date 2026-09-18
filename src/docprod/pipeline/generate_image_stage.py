from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from docprod.config import Settings, get_settings
from docprod.models.scene import Scene, ScenePlan
from docprod.planning.visual_bible import (
    VisualBible,
    derive_visual_bible,
    next_protagonist_memory,
    scene_includes_protagonist,
)
from docprod.providers.image_config import GeneratedImageManifest, ImageGenerationConfig
from docprod.providers.image_prompt import build_documentary_image_prompt, scene_neighbors
from docprod.providers.image_review import (
    ImageReviewRecord,
    ReviewState,
    load_review,
    set_review_state,
)
from docprod.providers.openai_image import OpenAIImageProvider, image_request_hash
from docprod.render.still import IMAGE_STRATEGIES, image_suffix_for_format
from docprod.storage.hashing import content_hash, file_sha256
from docprod.storage.json_store import atomic_write_bytes, load_model, save_model
from docprod.storage.paths import ProjectPaths

ProgressFn = Callable[[str], None]


def scene_source_hash(scene: Scene) -> str:
    return content_hash(
        {
            "id": scene.id,
            "visual_intent": scene.visual_intent,
            "narration": scene.narration,
            "mood": scene.mood.value,
            "primary_category": scene.metadata.get("primary_category"),
            "image_prompt": scene.generation.image_prompt,
            "negative_prompt": scene.generation.negative_prompt,
        }
    )


def _relative_output(paths: ProjectPaths, output: Path) -> str:
    try:
        return output.resolve().relative_to(paths.root.resolve()).as_posix()
    except ValueError:
        return str(output)


def _load_success_manifest(meta_path: Path) -> GeneratedImageManifest | None:
    if not meta_path.is_file():
        return None
    try:
        manifest = load_model(meta_path, GeneratedImageManifest)
    except (OSError, ValueError):
        return None
    if manifest.generation_status != "success":
        return None
    return manifest


def archive_active_still(
    paths: ProjectPaths,
    scene_id: str,
    *,
    archived_as: ReviewState,
) -> Path | None:
    """Copy the active still aside before a paid replacement. Never deletes history."""
    existing = _load_success_manifest(paths.scene_image_meta(scene_id))
    if existing is None or not existing.output_sha256:
        return None
    source = None
    for suffix in (".jpg", ".jpeg", ".png", ".webp"):
        candidate = paths.scene_image_path(scene_id, suffix=suffix)
        if candidate.is_file():
            source = candidate
            break
    if source is None:
        return None
    history_dir = paths.scene_image_history_dir(scene_id)
    history_dir.mkdir(parents=True, exist_ok=True)
    digest = existing.output_sha256
    archived = history_dir / f"{digest}{source.suffix}"
    archived.write_bytes(source.read_bytes())
    meta_src = paths.scene_image_meta(scene_id)
    if meta_src.is_file():
        (history_dir / f"{digest}.meta.json").write_bytes(meta_src.read_bytes())
    record = ImageReviewRecord(
        scene_id=scene_id,
        review_state=archived_as,
        artifact_sha256=digest,
        note=f"archived to history/{digest}{source.suffix}",
    )
    save_model(history_dir / f"{digest}.review.json", record)
    return archived


def load_or_create_visual_bible(paths: ProjectPaths, plan: ScenePlan) -> VisualBible:
    bible_path = paths.visual_bible_json()
    if bible_path.is_file():
        try:
            return load_model(bible_path, VisualBible)
        except (OSError, ValueError):
            pass
    bible = derive_visual_bible(plan)
    save_model(bible_path, bible)
    return bible


def image_file_matches(paths: ProjectPaths, scene_id: str, digest: str) -> bool:
    for suffix in (".jpg", ".jpeg", ".png", ".webp"):
        candidate = paths.scene_image_path(scene_id, suffix=suffix)
        if candidate.is_file() and file_sha256(candidate) == digest:
            return True
    return False


def should_skip_paid_generation(
    paths: ProjectPaths,
    scene: Scene,
    *,
    request_hash: str,
    force: bool,
) -> tuple[bool, str | None, GeneratedImageManifest | None]:
    """Return (skip, reason, existing_manifest). Force never skips."""
    existing = _load_success_manifest(paths.scene_image_meta(scene.id))
    if force:
        return False, None, existing
    review = load_review(paths, scene.id)
    if (
        existing is not None
        and review is not None
        and review.review_state == "approved"
        and existing.output_sha256
        and image_file_matches(paths, scene.id, existing.output_sha256)
    ):
        existing.cache_hit = True
        return True, "approved", existing
    if (
        existing is not None
        and existing.request_hash == request_hash
        and existing.output_sha256
        and image_file_matches(paths, scene.id, existing.output_sha256)
    ):
        existing.cache_hit = True
        return True, "cached", existing
    if review is not None and review.review_state == "rejected":
        return True, "rejected", existing
    return False, None, existing


def _previous_had_for_scene(plan: ScenePlan, bible: VisualBible, scene_id: str) -> bool:
    previous_had = False
    for item in plan.scenes:
        if item.id == scene_id:
            return previous_had
        _include, previous_had = next_protagonist_memory(item, bible, previous_had)
    return previous_had


def preview_image_prompt(
    paths: ProjectPaths,
    plan: ScenePlan,
    scene_id: str,
    *,
    settings: Settings | None = None,
    bible: VisualBible | None = None,
) -> tuple[str, str, bool]:
    scene = next((item for item in plan.scenes if item.id == scene_id), None)
    if scene is None:
        raise ValueError(f"Unknown scene id {scene_id!r}")
    visual_bible = bible if bible is not None else load_or_create_visual_bible(paths, plan)
    previous_had = _previous_had_for_scene(plan, visual_bible, scene_id)
    include = scene_includes_protagonist(
        scene, visual_bible, previous_had_protagonist=previous_had
    )
    previous_scene, next_scene = scene_neighbors(plan.scenes, scene_id)
    prompt = build_documentary_image_prompt(
        scene,
        bible=visual_bible,
        include_protagonist=include,
        previous_scene=previous_scene,
        next_scene=next_scene,
    )
    image_cfg = ImageGenerationConfig.from_settings(settings or get_settings())
    request_hash = image_request_hash(
        prompt=prompt, config=image_cfg, seed=scene.generation.seed
    )
    return prompt, request_hash, include


def execute_generate_image(
    paths: ProjectPaths,
    *,
    plan: ScenePlan,
    scene_id: str,
    confirm_paid: bool,
    force: bool = False,
    settings: Settings | None = None,
    provider: OpenAIImageProvider | None = None,
    bible: VisualBible | None = None,
    previous_had_protagonist: bool | None = None,
    archive_as: ReviewState = "superseded",
    progress: ProgressFn | None = None,
) -> GeneratedImageManifest:
    scene = next((item for item in plan.scenes if item.id == scene_id), None)
    if scene is None:
        raise ValueError(f"Unknown scene id {scene_id!r}")
    if scene.asset_strategy not in IMAGE_STRATEGIES:
        raise ValueError(
            f"Scene {scene_id} strategy is {scene.asset_strategy.value}, "
            "expected ai_image or ai_image_to_video"
        )
    cfg = settings or get_settings()
    image_cfg = ImageGenerationConfig.from_settings(cfg)
    visual_bible = bible if bible is not None else load_or_create_visual_bible(paths, plan)
    if previous_had_protagonist is None:
        previous_had_protagonist = _previous_had_for_scene(plan, visual_bible, scene_id)
    include = scene_includes_protagonist(
        scene, visual_bible, previous_had_protagonist=previous_had_protagonist
    )
    previous_scene, next_scene = scene_neighbors(plan.scenes, scene_id)
    prompt = build_documentary_image_prompt(
        scene,
        bible=visual_bible,
        include_protagonist=include,
        previous_scene=previous_scene,
        next_scene=next_scene,
    )
    seed = scene.generation.seed
    request_hash = image_request_hash(prompt=prompt, config=image_cfg, seed=seed)
    source_hash = scene_source_hash(scene)
    suffix = image_suffix_for_format(image_cfg.output_format)
    output_path = paths.scene_image_path(scene_id, suffix=suffix)
    skip, reason, existing = should_skip_paid_generation(
        paths, scene, request_hash=request_hash, force=force
    )
    if skip and existing is not None:
        existing.note = reason
        if progress:
            progress(f"Skip {scene_id} ({reason}); no paid image generation")
        return existing

    if existing is not None and image_file_matches(
        paths, scene_id, existing.output_sha256 or ""
    ):
        archive_active_still(paths, scene_id, archived_as=archive_as)

    adapter = provider or OpenAIImageProvider(settings=cfg, config=image_cfg)
    if progress:
        progress("PAID IMAGE REQUEST")
        progress(f"Provider: {image_cfg.provider}")
        progress(f"Model: {image_cfg.model}")
        progress(f"Scene: {scene_id}")
        progress(f"Strategy: {scene.asset_strategy.value}")
        progress(f"Size: {image_cfg.size}")
        progress(f"Quality: {image_cfg.quality}")
        progress(f"Prompt: {prompt}")
        progress(f"Request hash: {request_hash}")
        progress(f"Output: {output_path}")
    result = adapter.generate(prompt, confirm_paid=confirm_paid, seed=seed)
    paths.scene_visuals_dir(scene_id).mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(output_path, result.image_bytes)
    digest = file_sha256(output_path)
    manifest = GeneratedImageManifest(
        provider=image_cfg.provider,
        model=result.raw_model or image_cfg.model,
        scene_id=scene_id,
        prompt=prompt,
        size=image_cfg.size,
        quality=image_cfg.quality,
        output_format=image_cfg.output_format,
        seed_requested=seed,
        source_scene_hash=source_hash,
        request_hash=request_hash,
        output_path=_relative_output(paths, output_path),
        output_sha256=digest,
        revised_prompt=result.revised_prompt,
        usage=result.usage,
        generation_status="success",
        cache_hit=False,
        elapsed_seconds=round(result.elapsed_seconds, 3),
    )
    save_model(paths.scene_image_meta(scene_id), manifest)
    set_review_state(paths, scene_id, "generated", artifact_sha256=digest)
    if progress:
        progress(f"status: success in {manifest.elapsed_seconds:.3f}s")
        if manifest.usage:
            progress(f"usage: {manifest.usage}")
        else:
            progress("usage: not returned")
    return manifest
