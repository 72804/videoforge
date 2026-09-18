from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from docprod.config import Settings, get_settings
from docprod.models.enums import AssetStrategy
from docprod.models.scene import Scene, ScenePlan
from docprod.providers.image_config import GeneratedImageManifest, ImageGenerationConfig
from docprod.providers.image_prompt import build_documentary_image_prompt
from docprod.providers.openai_image import OpenAIImageProvider, image_request_hash
from docprod.render.still import image_suffix_for_format
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


def execute_generate_image(
    paths: ProjectPaths,
    *,
    plan: ScenePlan,
    scene_id: str,
    confirm_paid: bool,
    force: bool = False,
    settings: Settings | None = None,
    provider: OpenAIImageProvider | None = None,
    progress: ProgressFn | None = None,
) -> GeneratedImageManifest:
    scene = next((item for item in plan.scenes if item.id == scene_id), None)
    if scene is None:
        raise ValueError(f"Unknown scene id {scene_id!r}")
    if scene.asset_strategy is not AssetStrategy.ai_image:
        raise ValueError(
            f"Scene {scene_id} strategy is {scene.asset_strategy.value}, expected ai_image"
        )
    cfg = settings or get_settings()
    image_cfg = ImageGenerationConfig.from_settings(cfg)
    prompt = build_documentary_image_prompt(scene)
    if scene.generation.negative_prompt:
        prompt = f"{prompt} Avoid: {scene.generation.negative_prompt.strip()}."
    seed = scene.generation.seed
    request_hash = image_request_hash(prompt=prompt, config=image_cfg, seed=seed)
    source_hash = scene_source_hash(scene)
    suffix = image_suffix_for_format(image_cfg.output_format)
    output_path = paths.scene_image_path(scene_id, suffix=suffix)
    meta_path = paths.scene_image_meta(scene_id)
    existing = _load_success_manifest(meta_path)
    if (
        not force
        and existing is not None
        and existing.request_hash == request_hash
        and output_path.is_file()
        and file_sha256(output_path) == existing.output_sha256
    ):
        existing.cache_hit = True
        if progress:
            progress(f"Cache hit for {scene_id}; skipping paid image generation")
        return existing

    adapter = provider or OpenAIImageProvider(settings=cfg, config=image_cfg)
    if progress:
        progress("PAID IMAGE REQUEST")
        progress(f"Provider: {image_cfg.provider}")
        progress(f"Model: {image_cfg.model}")
        progress(f"Scene: {scene_id}")
        progress(f"Size: {image_cfg.size}")
        progress(f"Quality: {image_cfg.quality}")
        progress(f"Prompt: {prompt}")
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
    save_model(meta_path, manifest)
    if progress:
        progress(f"status: success in {manifest.elapsed_seconds:.3f}s")
        if manifest.usage:
            progress(f"usage: {manifest.usage}")
        else:
            progress("usage: not returned")
    return manifest
