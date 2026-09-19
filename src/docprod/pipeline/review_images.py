from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageDraw

from docprod.graphics.fonts import discover_sans_font, load_font
from docprod.models.enums import AssetStrategy
from docprod.models.project import Project
from docprod.models.scene import Scene, ScenePlan
from docprod.production import AssetPlan, AssetUnit
from docprod.production.info_graphics import is_named_person_scene
from docprod.production.prompts import NEGATIVE, historical_constraints, still_prompt_for
from docprod.providers.image_config import GeneratedImageManifest, ImageGenerationConfig
from docprod.providers.openai_image import OpenAIImageProvider, image_request_hash
from docprod.providers.request_budget import ModelRequestBudget
from docprod.storage.hashing import file_sha256
from docprod.storage.json_store import atomic_write_bytes, save_model
from docprod.storage.paths import PROMPT_VERSION, ProjectPaths

REVIEW_STYLE = (
    "Restrained documentary photograph, natural exposure, realistic materials, "
    "subtle cinematic composition, not glossy advertising, not hyper-dramatic, "
    "not obviously AI generated. Environmental storytelling. 16:9 landscape. "
    "No fake readable text, logos, watermarks, split panels, infographic styling, "
    "UI, diagrams, labels, or fabricated documents. "
    "Anonymous figures only; no invented likeness of a named real person. "
    "Hands believable, no motion blur, clear composition with room for camera motion."
)


def documentary_review_prompt(scene: Scene, *, keyframe: bool) -> str:
    base = still_prompt_for(scene)
    extra = " Strong starting keyframe for later image-to-video." if keyframe else ""
    banned = "; ".join(NEGATIVE)
    history = "; ".join(historical_constraints(scene))
    return f"{base} {REVIEW_STYLE}{extra} Must not show: {banned}. {history}"


def planned_image_units(asset_plan: AssetPlan, scenes: dict[str, Scene]) -> list[AssetUnit]:
    out: list[AssetUnit] = []
    for unit in asset_plan.units:
        scene = scenes[unit.scene_ids[0]]
        if is_named_person_scene(scene):
            continue
        if unit.source_strategy is AssetStrategy.generated_graphic:
            continue
        if unit.status in {"NEEDS_AI_IMAGE", "READY_AI_IMAGE"} or (
            unit.source_strategy is AssetStrategy.ai_image
        ):
            out.append(unit)
        elif (
            unit.status == "NEEDS_AI_VIDEO"
            or unit.source_strategy is AssetStrategy.ai_image_to_video
        ):
            out.append(unit)
    return out


@dataclass
class ImageJob:
    unit: AssetUnit
    scene: Scene
    keyframe: bool
    prompt: str
    request_hash: str
    output_path: object
    meta_path: object
    cached: bool


def plan_review_image_jobs(
    paths: ProjectPaths,
    *,
    plan: ScenePlan,
    asset_plan: AssetPlan,
    config: ImageGenerationConfig,
    seed: int,
) -> list[ImageJob]:
    scenes = {scene.id: scene for scene in plan.scenes}
    jobs: list[ImageJob] = []
    for unit in planned_image_units(asset_plan, scenes):
        scene = scenes[unit.scene_ids[0]]
        keyframe = unit.source_strategy is AssetStrategy.ai_image_to_video
        prompt = documentary_review_prompt(scene, keyframe=keyframe)
        request_hash = image_request_hash(
            prompt=prompt,
            config=config,
            seed=seed,
            extra={
                "asset_unit_id": unit.asset_unit_id,
                "prompt_version": PROMPT_VERSION,
                "historical": "|".join(historical_constraints(scene)),
                "kind": "keyframe" if keyframe else "still",
            },
        )
        if keyframe:
            output = paths.ai_keyframe_path(unit.asset_unit_id)
            meta = paths.ai_keyframe_meta(unit.asset_unit_id)
        else:
            output = paths.ai_unit_still_path(unit.asset_unit_id)
            meta = paths.ai_unit_still_meta(unit.asset_unit_id)
        cached = False
        if meta.is_file() and output.is_file():
            try:
                existing = GeneratedImageManifest.model_validate_json(meta.read_text())
                if existing.request_hash == request_hash and existing.output_sha256:
                    cached = file_sha256(output) == existing.output_sha256
            except (OSError, ValueError):
                cached = False
        jobs.append(
            ImageJob(
                unit=unit,
                scene=scene,
                keyframe=keyframe,
                prompt=prompt,
                request_hash=request_hash,
                output_path=output,
                meta_path=meta,
                cached=cached,
            )
        )
    return jobs


def generate_review_images(
    paths: ProjectPaths,
    *,
    project: Project,
    plan: ScenePlan,
    asset_plan: AssetPlan,
    confirm_paid: bool,
    provider: OpenAIImageProvider | None = None,
    budget: ModelRequestBudget | None = None,
) -> tuple[list[ImageJob], AssetPlan]:
    config = ImageGenerationConfig.from_settings()
    jobs = plan_review_image_jobs(
        paths, plan=plan, asset_plan=asset_plan, config=config, seed=project.random_seed
    )
    paid = [job for job in jobs if not job.cached]
    cap = budget.max_requests if budget is not None else len(paid)
    if len(paid) > cap:
        from docprod.exceptions import MaxPaidRequestsExceededError

        raise MaxPaidRequestsExceededError(
            f"Review images would make {len(paid)} paid calls, exceeding budget {cap}."
        )
    adapter = provider or OpenAIImageProvider(config=config)
    for job in jobs:
        if job.cached:
            continue
        if budget is not None:
            budget.reserve("image")
        result = adapter.generate(
            job.prompt, confirm_paid=confirm_paid, seed=project.random_seed, max_attempts=1
        )
        job.output_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(job.output_path, result.image_bytes)
        digest = file_sha256(job.output_path)
        rel = job.output_path.resolve().relative_to(paths.root.resolve()).as_posix()
        save_model(
            job.meta_path,
            GeneratedImageManifest(
                provider=config.provider,
                model=result.raw_model or config.model,
                scene_id=job.unit.asset_unit_id,
                prompt=job.prompt,
                size=config.size,
                quality=config.quality,
                output_format=config.output_format,
                seed_requested=project.random_seed,
                source_scene_hash=job.request_hash,
                request_hash=job.request_hash,
                output_path=rel,
                output_sha256=digest,
                revised_prompt=result.revised_prompt,
                usage=result.usage,
                generation_status="success",
                cache_hit=False,
                elapsed_seconds=round(result.elapsed_seconds, 3),
            ),
        )
    updated: list[AssetUnit] = []
    by_id = {job.unit.asset_unit_id: job for job in jobs}
    for unit in asset_plan.units:
        job = by_id.get(unit.asset_unit_id)
        if job is None:
            updated.append(unit)
            continue
        rel = job.output_path.resolve().relative_to(paths.root.resolve()).as_posix()
        if job.keyframe:
            updated.append(
                unit.model_copy(
                    update={
                        "status": "READY_AI_KEYFRAME",
                        "provider": "openai",
                        "source_path": rel,
                        "extra": {
                            **unit.extra,
                            "planned_strategy": "ai_image_to_video",
                            "runtime_preview_strategy": "ai_keyframe_preview",
                        },
                    }
                )
            )
        else:
            updated.append(
                unit.model_copy(
                    update={
                        "status": "READY_AI_IMAGE",
                        "provider": "openai",
                        "source_path": rel,
                    }
                )
            )
    return jobs, asset_plan.model_copy(update={"units": updated})


def write_paid_visuals_sheet(paths: ProjectPaths, jobs: list[ImageJob]) -> None:
    if not jobs:
        return
    tile_w, tile_h, label_h = 480, 270, 70
    cols = min(3, len(jobs))
    rows = (len(jobs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tile_w, rows * (tile_h + label_h)), (12, 12, 14))
    draw = ImageDraw.Draw(sheet)
    font = load_font(discover_sans_font(), 14)
    for index, job in enumerate(jobs):
        col = index % cols
        row = index // cols
        x = col * tile_w
        y = row * (tile_h + label_h)
        if job.output_path.is_file():
            try:
                image = Image.open(job.output_path).convert("RGB")
            except OSError:
                image = None
            if image is not None:
                image.thumbnail((tile_w, tile_h))
                sheet.paste(
                    image,
                    (x + (tile_w - image.width) // 2, y + (tile_h - image.height) // 2),
                )
        kind = "keyframe" if job.keyframe else "still"
        caption = (
            f"{job.unit.asset_unit_id} {kind}\n"
            f"{','.join(job.unit.scene_ids)}\n{job.unit.visual_concept[:60]}"
        )
        draw.multiline_text((x + 8, y + tile_h + 4), caption, font=font, fill=(230, 230, 230))
    dest = paths.paid_visuals_contact_sheet()
    dest.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(dest, "JPEG", quality=85)
