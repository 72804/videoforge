from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from docprod.config import Settings, get_settings
from docprod.drama.story import CHARACTER_REF_PLAN
from docprod.drama.uniqueness import collage_violations
from docprod.models.enums import AssetStrategy
from docprod.models.scene import Scene, ScenePlan
from docprod.providers.image_config import GeneratedImageManifest, ImageGenerationConfig
from docprod.providers.openai_image import OpenAIImageProvider, image_request_hash
from docprod.providers.paid_cache import PaidArtifactCache
from docprod.providers.veo_mapping import average_hash, hash_similarity
from docprod.render.contact_sheet import build_contact_sheet
from docprod.storage.hashing import file_sha256
from docprod.storage.json_store import atomic_write_bytes, load_model, save_json, save_model
from docprod.storage.paths import ProjectPaths

ProgressFn = Callable[[str], None]
CACHE_KIND = "openai_image"
NEAR_DUP_THRESHOLD = 0.92
IDENTITY = (
    "Preserve the attached reference identity: same face, age, hair, and core appearance. "
    "Allow a new pose, camera, expression, lighting, and shot size. "
    "Do not copy the reference portrait composition. Do not add text, labels, collage, "
    "grids, split panels, storyboards, or fake UI."
)
REF_TRAITS = {
    "ref_kemal": (
        "Quiet ordinary Turkish neighborhood man, trustworthy, slightly tired, "
        "understated, not goofy, not caricatured, looks underestimated."
    ),
    "ref_birko": (
        "Charismatic, self-confident, slightly overdressed for the neighborhood, "
        "well-groomed, annoyingly comfortable, subtle vanity, plausible not visually evil."
    ),
    "ref_muge": (
        "Independent adult woman, observant, emotionally bored with routine, grounded, "
        "attractive in a normal realistic way, not glamour-model, not helpless."
    ),
}


@dataclass
class DramaVisualJob:
    job_id: str
    kind: str
    prompt: str
    seed: int | None
    request_hash: str
    output_path: Path
    meta_path: Path
    scene_id: str | None = None
    character_ids: tuple[str, ...] = ()
    reference_paths: list[Path] = field(default_factory=list)


@dataclass
class DramaVisualResult:
    model: str
    raw_model: str
    quality: str
    size: str
    ref_count: int
    timeline_count: int
    paid_calls: int
    cache_hits: int
    cache_entries: int
    failed: list[str]
    usages: list[dict]
    estimated_usd: float
    measured_usd: float | None
    ref_paths: dict[str, str]
    timeline_dir: str
    contact_sheet: str | None
    duplicate_count: int
    near_duplicate_warnings: list[tuple[str, str, float]]
    collage_violations: list[str]
    missing_character_consistency: list[str]
    report_path: Path


def _cost_from_usage(usage: dict | None) -> float | None:
    if not usage:
        return None
    text_in = usage.get("input_tokens") or usage.get("text_tokens")
    image_out = usage.get("output_tokens")
    image_in = 0
    details = usage.get("input_tokens_details")
    if isinstance(details, dict):
        image_in = details.get("image_tokens") or 0
        text_in = details.get("text_tokens") or text_in
    if text_in is None and image_out is None:
        return None
    total = float(text_in or 0) * 5 / 1_000_000
    total += float(image_in or 0) * 8 / 1_000_000
    total += float(image_out or 0) * 30 / 1_000_000
    return round(total, 6)


def character_ref_dir(paths: ProjectPaths) -> Path:
    return paths.visuals_dir / "character_refs"


def _existing_ok(meta_path: Path, output: Path, request_hash: str) -> GeneratedImageManifest | None:
    if not meta_path.is_file() or not output.is_file():
        return None
    try:
        manifest = load_model(meta_path, GeneratedImageManifest)
    except (OSError, ValueError):
        return None
    if manifest.generation_status != "success":
        return None
    if manifest.request_hash != request_hash:
        return None
    if file_sha256(output) != manifest.output_sha256:
        return None
    manifest.cache_hit = True
    return manifest


def _ref_prompt(item: dict) -> str:
    extra = REF_TRAITS.get(str(item["id"]), "")
    return (
        f"{item['prompt']} {extra} Photorealistic cinematic Turkish-neighborhood realism. "
        "One person, one coherent frame, no labels, no multi-pose sheet, no collage, "
        "no model-sheet layout, no text inside the image."
    )


def _timeline_prompt(scene: Scene, character_ids: tuple[str, ...]) -> str:
    names = {
        "kemal": "Baby Kemal",
        "birko": "Hain Birko",
        "muge": "Müge",
    }
    prompt = (scene.generation.image_prompt or scene.visual_intent).strip()
    if character_ids:
        labeled = ", ".join(
            f"reference image {index + 1} is {names.get(cid, cid)}"
            for index, cid in enumerate(character_ids)
        )
        prompt = f"{prompt} {IDENTITY} Attached references: {labeled}."
    if scene.generation.negative_prompt:
        prompt = f"{prompt} Also avoid: {scene.generation.negative_prompt}."
    return prompt


def plan_drama_visual_jobs(
    paths: ProjectPaths,
    plan: ScenePlan,
    *,
    settings: Settings | None = None,
) -> tuple[list[DramaVisualJob], ImageGenerationConfig]:
    image_cfg = ImageGenerationConfig.from_settings(settings or get_settings())
    fmt = image_cfg.output_format
    suffix = fmt if fmt.startswith(".") else f".{fmt}"
    if suffix == ".jpeg":
        suffix = ".jpg"
    jobs: list[DramaVisualJob] = []
    ref_dir = character_ref_dir(paths)
    for index, item in enumerate(CHARACTER_REF_PLAN):
        prompt = _ref_prompt(item)
        request_hash = image_request_hash(
            prompt=prompt,
            config=image_cfg,
            seed=9000 + index,
            extra={"kind": "character_ref", "id": str(item["id"])},
        )
        output = ref_dir / f"{item['id']}{suffix}"
        jobs.append(
            DramaVisualJob(
                job_id=str(item["id"]),
                kind="character_ref",
                prompt=prompt,
                seed=9000 + index,
                request_hash=request_hash,
                output_path=output,
                meta_path=ref_dir / f"{item['id']}.meta.json",
            )
        )
    stills = [scene for scene in plan.scenes if scene.asset_strategy == AssetStrategy.ai_image]
    for scene in stills:
        character_ids = tuple(str(item) for item in (scene.metadata.get("characters") or []))
        prompt = _timeline_prompt(scene, character_ids)
        extra = {
            "kind": "timeline",
            "scene": scene.id,
            "refs": ",".join(character_ids),
        }
        request_hash = image_request_hash(
            prompt=prompt,
            config=image_cfg,
            seed=scene.generation.seed,
            extra=extra,
        )
        output = paths.scene_image_path(scene.id, suffix=suffix)
        jobs.append(
            DramaVisualJob(
                job_id=scene.id,
                kind="timeline",
                prompt=prompt,
                seed=scene.generation.seed,
                request_hash=request_hash,
                output_path=output,
                meta_path=paths.scene_image_meta(scene.id),
                scene_id=scene.id,
                character_ids=character_ids,
            )
        )
    return jobs, image_cfg


def _bind_references(jobs: list[DramaVisualJob]) -> None:
    by_character: dict[str, Path] = {}
    for job in jobs:
        if job.kind != "character_ref":
            continue
        by_character[job.job_id.removeprefix("ref_")] = job.output_path
    for job in jobs:
        if job.kind != "timeline":
            continue
        job.reference_paths = [
            by_character[cid] for cid in job.character_ids if cid in by_character
        ]


def _write_from_cache(
    job: DramaVisualJob,
    cached: tuple[Path, dict],
    image_cfg: ImageGenerationConfig,
) -> GeneratedImageManifest:
    payload = cached[0].read_bytes()
    job.output_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(job.output_path, payload)
    digest = file_sha256(job.output_path)
    usage = cached[1].get("usage") if isinstance(cached[1].get("usage"), dict) else None
    manifest = GeneratedImageManifest(
        provider=image_cfg.provider,
        model=str(cached[1].get("model") or image_cfg.model),
        scene_id=job.scene_id or job.job_id,
        prompt=job.prompt,
        size=image_cfg.size,
        quality=image_cfg.quality,
        output_format=image_cfg.output_format,
        seed_requested=job.seed,
        source_scene_hash=job.request_hash,
        request_hash=job.request_hash,
        output_path=str(job.output_path),
        output_sha256=digest,
        usage=usage,
        generation_status="success",
        cache_hit=True,
        note="paid_cache",
    )
    save_model(job.meta_path, manifest)
    return manifest


def execute_generate_drama_visuals(
    paths: ProjectPaths,
    *,
    plan: ScenePlan,
    confirm_paid: bool,
    settings: Settings | None = None,
    provider: OpenAIImageProvider | None = None,
    cache: PaidArtifactCache | None = None,
    progress: ProgressFn | None = None,
    stop_on_failure: bool = True,
    max_paid_requests: int = 24,
) -> DramaVisualResult:
    cfg = settings or get_settings()
    jobs, image_cfg = plan_drama_visual_jobs(paths, plan, settings=cfg)
    _bind_references(jobs)
    stills = [job for job in jobs if job.kind == "timeline"]
    refs = [job for job in jobs if job.kind == "character_ref"]
    hist = 0.06698
    if progress:
        progress("DRAMA VISUAL GENERATION PLAN (not yet calling API)")
        progress(f"model={image_cfg.model}")
        progress(f"quality={image_cfg.quality}")
        progress(f"resolution={image_cfg.size}")
        progress(f"planned_generation_count={len(jobs)}")
        progress(f"character_refs={len(refs)} timeline={len(stills)}")
        progress("KNOWN token rates $5/$8/$30 per 1M (text in / image in / image out)")
        progress(f"historical_estimate={len(jobs)}×${hist:.5f}=${len(jobs) * hist:.4f}")
        progress("title_cards=local only; no image spend")
    collage = collage_violations(plan)
    adapter = provider or OpenAIImageProvider(settings=cfg, config=image_cfg)
    paid_cache = cache or PaidArtifactCache()
    paid_calls = 0
    cache_hits = 0
    cache_entries = 0
    failed: list[str] = []
    usages: list[dict] = []
    raw_model = image_cfg.model
    for job in jobs:
        if job.kind == "timeline":
            job.reference_paths = [path for path in job.reference_paths if path.is_file()]
            extra = {
                "kind": job.kind,
                "refs": ",".join(file_sha256(path) for path in job.reference_paths),
            }
            job.request_hash = image_request_hash(
                prompt=job.prompt,
                config=image_cfg,
                seed=job.seed,
                extra=extra,
            )
        existing = _existing_ok(job.meta_path, job.output_path, job.request_hash)
        if existing is not None:
            cache_hits += 1
            if existing.usage:
                usages.append(existing.usage)
            raw_model = existing.model or raw_model
            if progress:
                progress(f"CACHE {job.job_id} local meta")
            continue
        cached = paid_cache.get(CACHE_KIND, job.request_hash)
        if cached is not None:
            manifest = _write_from_cache(job, cached, image_cfg)
            cache_hits += 1
            cache_entries += 1
            if manifest.usage:
                usages.append(manifest.usage)
            raw_model = manifest.model or raw_model
            if progress:
                progress(f"CACHE {job.job_id} paid_cache")
            continue
        if progress:
            progress(f"PAID IMAGE REQUEST {job.job_id} kind={job.kind}")
            progress(f"Prompt: {job.prompt}")
            if job.reference_paths:
                progress(f"References: {', '.join(path.name for path in job.reference_paths)}")
        if paid_calls >= max_paid_requests:
            failed.append(f"{job.job_id}: max_paid_requests {max_paid_requests} reached")
            break
        try:
            result = adapter.generate(
                job.prompt,
                confirm_paid=confirm_paid,
                seed=job.seed,
                reference_images=job.reference_paths or None,
            )
        except Exception as exc:
            failed.append(f"{job.job_id}: {exc}")
            if progress:
                progress(f"FAILED {job.job_id}: {exc}")
            if stop_on_failure:
                break
            continue
        paid_calls += 1
        raw_model = result.raw_model or raw_model
        job.output_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(job.output_path, result.image_bytes)
        digest = file_sha256(job.output_path)
        if result.usage:
            usages.append(result.usage)
        try:
            rel_out = job.output_path.resolve().relative_to(paths.root.resolve()).as_posix()
        except ValueError:
            rel_out = str(job.output_path)
        manifest = GeneratedImageManifest(
            provider=image_cfg.provider,
            model=result.raw_model or image_cfg.model,
            scene_id=job.scene_id or job.job_id,
            prompt=job.prompt,
            size=image_cfg.size,
            quality=image_cfg.quality,
            output_format=image_cfg.output_format,
            seed_requested=job.seed,
            source_scene_hash=job.request_hash,
            request_hash=job.request_hash,
            output_path=rel_out,
            output_sha256=digest,
            revised_prompt=result.revised_prompt,
            usage=result.usage,
            generation_status="success",
            cache_hit=False,
            elapsed_seconds=round(result.elapsed_seconds, 3),
            note="character_ref" if job.kind == "character_ref" else "timeline",
        )
        save_model(job.meta_path, manifest)
        paid_cache.put(
            CACHE_KIND,
            job.request_hash,
            result.image_bytes,
            suffix=job.output_path.suffix,
            meta={
                "model": manifest.model,
                "scene_id": manifest.scene_id,
                "kind": job.kind,
            },
        )
        cache_entries += 1
        if progress:
            progress(f"status: success {job.job_id} sha256={digest[:12]}")
    missing: list[str] = []
    timeline_paths: list[tuple[str, Path]] = []
    for job in stills:
        if not job.output_path.is_file():
            missing.append(job.job_id)
            continue
        timeline_paths.append((job.job_id, job.output_path))
        if job.character_ids and not job.reference_paths:
            missing.append(f"{job.job_id}:refs")
    hashes: dict[str, str] = {}
    dupes = 0
    for scene_id, path in timeline_paths:
        digest = file_sha256(path)
        if digest in hashes.values():
            dupes += 1
        hashes[scene_id] = digest
    near: list[tuple[str, str, float]] = []
    ah: dict[str, list[int]] = {}
    for scene_id, path in timeline_paths:
        try:
            ah[scene_id] = average_hash(path)
        except Exception:
            pass
        try:
            with Image.open(path) as image:
                if image.size != (image_cfg.width, image_cfg.height):
                    missing.append(f"{scene_id}:size={image.size}")
        except Exception:
            missing.append(f"{scene_id}:unreadable")
    ids = list(ah)
    for i, left in enumerate(ids):
        for right in ids[i + 1 :]:
            score = hash_similarity(ah[left], ah[right])
            if score >= NEAR_DUP_THRESHOLD:
                near.append((left, right, round(score, 3)))
    sheet_entries: list[tuple[str, str, Path]] = []
    for job in refs:
        if job.output_path.is_file():
            sheet_entries.append((job.job_id, "ref", job.output_path))
    for scene_id, path in timeline_paths:
        sheet_entries.append((scene_id, "timeline", path))
    sheet = None
    if sheet_entries:
        dest = paths.review_dir / "drama_full_visual_contact_sheet.jpg"
        try:
            sheet = build_contact_sheet(paths, sheet_entries, output=dest, columns=5)
        except Exception as exc:
            if progress:
                progress(f"contact sheet failed: {exc}")
    measured_parts = [_cost_from_usage(item) for item in usages]
    known = [part for part in measured_parts if part is not None]
    measured = None
    if known and len(known) == len(measured_parts) and len(known) == paid_calls + cache_hits:
        measured = round(sum(known), 6)
    elif known:
        measured = round(sum(known), 6)
    ref_paths = {
        job.job_id: str(job.output_path) for job in refs if job.output_path.is_file()
    }
    report = {
        "model": image_cfg.model,
        "raw_model": raw_model,
        "quality": image_cfg.quality,
        "size": image_cfg.size,
        "paid_calls": paid_calls,
        "cache_hits": cache_hits,
        "failed": failed,
        "duplicate_count": dupes,
        "near_duplicates": near,
        "collage_violations": collage,
        "missing": missing,
        "usages": usages,
    }
    report_path = paths.review_dir / "drama_visual_generation_report.json"
    save_json(report_path, report)
    return DramaVisualResult(
        model=image_cfg.model,
        raw_model=raw_model,
        quality=image_cfg.quality,
        size=image_cfg.size,
        ref_count=len(refs),
        timeline_count=len(stills),
        paid_calls=paid_calls,
        cache_hits=cache_hits,
        cache_entries=cache_entries,
        failed=failed,
        usages=usages,
        estimated_usd=round(len(jobs) * hist, 4),
        measured_usd=measured,
        ref_paths=ref_paths,
        timeline_dir=str(paths.visuals_dir),
        contact_sheet=str(sheet) if sheet else None,
        duplicate_count=dupes,
        near_duplicate_warnings=near,
        collage_violations=collage,
        missing_character_consistency=missing,
        report_path=report_path,
    )
