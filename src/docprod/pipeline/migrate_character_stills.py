from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image

from docprod.config import Settings, get_settings
from docprod.drama.timeline import is_title_card
from docprod.models.scene import Scene, ScenePlan
from docprod.pipeline.generate_drama_visuals import _cost_from_usage
from docprod.providers.image_config import GeneratedImageManifest, ImageGenerationConfig
from docprod.providers.openai_image import (
    OPENAI_IMAGE_EDIT_MAX_REFERENCE_FILES,
    OpenAIImageProvider,
    image_request_hash,
)
from docprod.providers.paid_cache import PaidArtifactCache
from docprod.providers.pricing import (
    BIRKO_DRAMA_IMAGE_ATTRIBUTABLE_USD,
    BIRKO_DRAMA_IMAGE_PAID_CALLS,
    IMAGE_MIGRATION_CONSERVATIVE_CALL_USD,
    IMAGE_MIGRATION_HARD_CAP_USD,
    MAPLE_7_IMAGE_BATCH_TOTAL_USD,
    OPENAI_IMAGE_TOKEN_RATES_NOTE,
    V2_VIDEO_TOTAL_USD,
    birko_implied_image_unit_usd,
    estimated_image_migration_usd,
)
from docprod.quality.character_refs import (
    bind_scene_identity_references,
    plan_character_migration,
)
from docprod.quality.enums import CostConfidence
from docprod.render.contact_sheet import build_contact_sheet
from docprod.storage.hashing import file_sha256
from docprod.storage.json_store import atomic_write_bytes, load_model, save_json, save_model
from docprod.storage.paths import ProjectPaths

CACHE_KIND = "openai_image"
DISPLAY = {"birko": "Birko", "kemal": "Kemal", "muge": "Müge"}
IDENTITY_RULES = (
    "Use attached images ONLY as identity sources (face, age, hair, core appearance). "
    "Do not copy portrait/phone aspect ratio, original background, clothing, lighting, "
    "or pose. Output a cinematic 16:9 still that preserves this scene's narrative purpose, "
    "location, composition concept, camera, action, emotional beat, and style. "
    "Replace prior generated likenesses with the labeled identities. "
    "Keep identities distinct; no face blending."
)


@dataclass
class StillMigrationJob:
    scene_id: str
    beat_id: str
    characters: list[str]
    references: list[str]
    reference_count: int
    identity_versions: dict[str, str]
    generation_model: str
    output_path: str
    v1_still: str
    prompt: str
    request_hash: str
    seed: int | None


@dataclass
class StillMigrationPreflight:
    jobs: list[StillMigrationJob]
    model: str
    calls: int
    cache_hits: int
    cost_confidence: str
    estimated_usd: float | None
    hard_cap_usd: float
    video_usd: float
    notes: list[str] = field(default_factory=list)
    b15_all_three_refs: bool = False


def i2v_start_image_path(
    paths: ProjectPaths, scene: Scene, *, require_custom: bool = False
) -> Path:
    """I2V start frame. Character scenes must use approved custom_v2 stills."""
    custom = paths.custom_v2_scene_image(scene.id)
    chars = list((scene.metadata or {}).get("characters") or [])
    if custom.is_file():
        return custom
    if require_custom or chars:
        raise RuntimeError(
            f"{scene.id} missing approved custom_v2 still; refusing V1 identity fallback"
        )
    return paths.scene_image_path(scene.id)


def _identity_prompt(scene: Scene, bound: list[tuple[str, Path, str]]) -> str:
    base = (scene.generation.image_prompt or scene.visual_intent).strip()
    labels = ", ".join(
        f"reference image {index + 1} is {DISPLAY.get(cid, cid)} "
        f"(identity only; do not copy that photo's framing)"
        for index, (cid, _path, _ver) in enumerate(bound)
    )
    prompt = f"{base} {IDENTITY_RULES} Attached references: {labels}."
    if scene.generation.negative_prompt:
        prompt = f"{prompt} Also avoid: {scene.generation.negative_prompt}."
    return prompt


def build_still_migration_jobs(
    paths: ProjectPaths,
    plan: ScenePlan,
    *,
    settings: Settings | None = None,
) -> list[StillMigrationJob]:
    cfg = ImageGenerationConfig.from_settings(settings or get_settings())
    rows = {row.scene_id: row for row in plan_character_migration(paths, plan)}
    jobs: list[StillMigrationJob] = []
    for scene in plan.scenes:
        if is_title_card(scene):
            continue
        row = rows.get(scene.id)
        if row is None or not row.regeneration_required:
            continue
        chars = list(row.characters)
        bound = bind_scene_identity_references(
            paths, chars, provider="openai", task="image"
        )
        if len(bound) != len(chars):
            raise ValueError(f"{scene.id}: identity drop {chars} vs {bound}")
        prompt = _identity_prompt(scene, bound)
        ref_paths = [path for _cid, path, _ver in bound]
        versions = {cid: ver for cid, _path, ver in bound}
        extra = {
            "kind": "custom_identity_still",
            "scene": scene.id,
            "visual_version": "custom_v2",
            "refs": ",".join(file_sha256(path) for path in ref_paths),
            "identity_versions": ",".join(f"{cid}:{ver}" for cid, ver in versions.items()),
        }
        digest = image_request_hash(
            prompt=prompt,
            config=cfg,
            seed=scene.generation.seed,
            extra=extra,
        )
        dest = paths.custom_v2_scene_image(scene.id)
        jobs.append(
            StillMigrationJob(
                scene_id=scene.id,
                beat_id=str((scene.metadata or {}).get("beat_id") or ""),
                characters=chars,
                references=[
                    path.relative_to(paths.root).as_posix()
                    if path.is_relative_to(paths.root)
                    else str(path)
                    for path in ref_paths
                ],
                reference_count=len(ref_paths),
                identity_versions=versions,
                generation_model=cfg.model,
                output_path=dest.relative_to(paths.root).as_posix()
                if dest.is_relative_to(paths.root)
                else str(dest),
                v1_still=paths.scene_image_path(scene.id).relative_to(paths.root).as_posix(),
                prompt=prompt,
                request_hash=digest,
                seed=scene.generation.seed,
            )
        )
    return jobs


def preflight_still_migration(
    paths: ProjectPaths,
    plan: ScenePlan,
    *,
    settings: Settings | None = None,
    hard_cap_usd: float = IMAGE_MIGRATION_HARD_CAP_USD,
) -> StillMigrationPreflight:
    cfg = ImageGenerationConfig.from_settings(settings or get_settings())
    jobs = build_still_migration_jobs(paths, plan, settings=settings)
    cache = PaidArtifactCache()
    hits = 0
    for job in jobs:
        dest = paths.root / job.output_path
        meta = paths.custom_v2_scene_meta(job.scene_id)
        if dest.is_file() and meta.is_file():
            try:
                loaded = load_model(meta, GeneratedImageManifest)
            except (OSError, ValueError):
                loaded = None
            if loaded and loaded.request_hash == job.request_hash:
                hits += 1
                continue
        if cache.get(CACHE_KIND, job.request_hash) is not None:
            hits += 1
    b15 = next((job for job in jobs if job.beat_id == "b15"), None)
    notes = [
        f"Maple ${MAPLE_7_IMAGE_BATCH_TOTAL_USD} = 7-image BATCH total, not per-image.",
        f"Birko {BIRKO_DRAMA_IMAGE_PAID_CALLS} image calls attributable "
        f"${BIRKO_DRAMA_IMAGE_ATTRIBUTABLE_USD} "
        f"(~${birko_implied_image_unit_usd()}/call observed).",
        OPENAI_IMAGE_TOKEN_RATES_NOTE,
        "Reference images add image-in tokens; Birko implied unit may understate.",
        f"OpenAI adapter max reference files: {OPENAI_IMAGE_EDIT_MAX_REFERENCE_FILES} "
        "(list to images.edit; no silent drop).",
        f"Hard image-spend cap: ${hard_cap_usd:.2f} (operational, not a list price).",
        f"Later video upgrade (Veo+Gen-4.5): ${V2_VIDEO_TOTAL_USD:.2f}.",
        "Outputs go to artifacts/visuals/custom_v2/; V1 stills are never overwritten.",
    ]
    return StillMigrationPreflight(
        jobs=jobs,
        model=cfg.model,
        calls=len(jobs),
        cache_hits=hits,
        cost_confidence=CostConfidence.ESTIMATED.value,
        estimated_usd=estimated_image_migration_usd(len(jobs) - hits),
        hard_cap_usd=hard_cap_usd,
        video_usd=V2_VIDEO_TOTAL_USD,
        notes=notes,
        b15_all_three_refs=bool(
            b15 and b15.reference_count == 3 and set(b15.characters) == {"birko", "muge", "kemal"}
        ),
    )


def write_migration_preflight(
    paths: ProjectPaths, preflight: StillMigrationPreflight
) -> tuple[Path, Path]:
    payload: dict[str, Any] = {
        "model": preflight.model,
        "calls": preflight.calls,
        "cache_hits": preflight.cache_hits,
        "cost_confidence": preflight.cost_confidence,
        "estimated_usd_from_birko_usage": preflight.estimated_usd,
        "hard_cap_usd": preflight.hard_cap_usd,
        "video_usd": preflight.video_usd,
        "prospective_combined_new_spend": {
            "image_estimated": preflight.estimated_usd,
            "image_hard_cap": preflight.hard_cap_usd,
            "video_known": preflight.video_usd,
            "combined_if_estimate_holds": round(
                (preflight.estimated_usd or 0) + preflight.video_usd, 4
            ),
            "combined_if_image_hits_cap": round(
                preflight.hard_cap_usd + preflight.video_usd, 4
            ),
        },
        "b15_all_three_refs": preflight.b15_all_three_refs,
        "notes": preflight.notes,
        "jobs": [
            {
                "scene_id": job.scene_id,
                "beat_id": job.beat_id,
                "characters": job.characters,
                "custom_reference_files": job.references,
                "number_of_references": job.reference_count,
                "generation_model": job.generation_model,
                "output_path": job.output_path,
                "v1_still": job.v1_still,
                "identity_versions": job.identity_versions,
                "request_hash": job.request_hash,
            }
            for job in preflight.jobs
        ],
        "paid_calls": 0,
    }
    json_path = paths.review_dir / "character_still_migration_preflight.json"
    md_path = paths.review_dir / "character_still_migration_preflight.md"
    paths.review_dir.mkdir(parents=True, exist_ok=True)
    save_json(json_path, payload)
    lines = [
        "# Custom-character still migration preflight",
        "",
        f"Calls: {preflight.calls}",
        f"Model: {preflight.model}",
        f"Cache hits: {preflight.cache_hits}",
        f"Cost confidence: {preflight.cost_confidence}",
        f"Estimated image USD (Birko usage scaled): {preflight.estimated_usd}",
        f"Hard image cap: ${preflight.hard_cap_usd:.2f}",
        f"Later video: ${preflight.video_usd:.2f}",
        f"b15 all 3 refs: {str(preflight.b15_all_three_refs).lower()}",
        "",
        *[f"- {note}" for note in preflight.notes],
        "",
    ]
    for job in preflight.jobs:
        lines.extend(
            [
                f"## {job.scene_id} ({job.beat_id})",
                f"- characters: {', '.join(job.characters)}",
                f"- custom references ({job.reference_count}): {job.references}",
                f"- model: {job.generation_model}",
                f"- output: {job.output_path}",
                f"- identity versions: {job.identity_versions}",
                "",
            ]
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def _custom_ref_hashes(paths: ProjectPaths, job: StillMigrationJob) -> dict[str, str]:
    out: dict[str, str] = {}
    for rel in job.references:
        path = paths.root / rel
        if not path.is_file():
            raise RuntimeError(f"Missing custom reference {rel}")
        if "character_refs" in Path(rel).as_posix():
            raise RuntimeError(f"Refusing generated portrait as identity: {rel}")
        if "inputs/characters/" not in Path(rel).as_posix():
            raise RuntimeError(f"Identity ref must be a locked custom input: {rel}")
        out[rel] = file_sha256(path)
    if len(out) != len(job.characters):
        raise RuntimeError(
            f"{job.scene_id}: would drop identities {job.characters} vs {list(out)}"
        )
    return out


def _write_still_manifest(
    *,
    job: StillMigrationJob,
    image_cfg: ImageGenerationConfig,
    meta: Path,
    digest: str,
    ref_hashes: dict[str, str],
    usage: dict[str, int | float | str] | None,
    model: str,
    cache_hit: bool,
) -> None:
    save_model(
        meta,
        GeneratedImageManifest(
            provider=image_cfg.provider,
            model=model,
            scene_id=job.scene_id,
            prompt=job.prompt,
            size=image_cfg.size,
            quality=image_cfg.quality,
            output_format=image_cfg.output_format,
            seed_requested=job.seed,
            source_scene_hash=job.request_hash,
            request_hash=job.request_hash,
            output_path=job.output_path,
            output_sha256=digest,
            usage=usage,
            generation_status="success",
            cache_hit=cache_hit,
            character_identity_versions=job.identity_versions,
            reference_paths=list(job.references),
            reference_sha256=ref_hashes,
            note="custom_v2_identity;refs=" + ",".join(job.references),
        ),
    )


def _append_journal(paths: ProjectPaths, record: dict[str, Any]) -> None:
    dest = paths.review_dir / "character_still_migration_journal.json"
    paths.review_dir.mkdir(parents=True, exist_ok=True)
    existing: list[Any] = []
    if dest.is_file():
        try:
            loaded = json.loads(dest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            loaded = []
        if isinstance(loaded, list):
            existing = loaded
    record = dict(record)
    record["updated_at"] = datetime.now(UTC).isoformat()
    existing.append(record)
    save_json(dest, existing)


def execute_still_migration(
    paths: ProjectPaths,
    plan: ScenePlan,
    *,
    confirm_paid: bool,
    settings: Settings | None = None,
    hard_cap_usd: float = IMAGE_MIGRATION_HARD_CAP_USD,
    progress: Any | None = None,
    provider: OpenAIImageProvider | None = None,
    cache: PaidArtifactCache | None = None,
) -> dict[str, Any]:
    log = progress or (lambda _msg: None)
    pre = preflight_still_migration(paths, plan, settings=settings, hard_cap_usd=hard_cap_usd)
    write_migration_preflight(paths, pre)
    if not confirm_paid:
        return {
            "executed": False,
            "paid_calls": 0,
            "preflight": True,
            "calls_planned": pre.calls,
        }
    v1_before = {
        job.scene_id: file_sha256(paths.root / job.v1_still)
        for job in pre.jobs
        if (paths.root / job.v1_still).is_file()
    }
    cfg = settings or get_settings()
    image_cfg = ImageGenerationConfig.from_settings(cfg)
    adapter = provider or OpenAIImageProvider(settings=cfg, config=image_cfg)
    cache = cache or PaidArtifactCache()
    paid = 0
    attempted = 0
    local_hits = 0
    recovered = 0
    failures: list[str] = []
    spent = 0.0
    stop_reason = ""
    pending = 0
    for job in pre.jobs:
        dest = paths.custom_v2_scene_image(job.scene_id)
        meta = paths.custom_v2_scene_meta(job.scene_id)
        already = False
        if dest.is_file() and meta.is_file():
            try:
                loaded = load_model(meta, GeneratedImageManifest)
            except (OSError, ValueError):
                loaded = None
            already = bool(
                loaded
                and loaded.request_hash == job.request_hash
                and loaded.generation_status == "success"
            )
        if not already and cache.get(CACHE_KIND, job.request_hash) is None:
            pending += 1
    conservative = IMAGE_MIGRATION_CONSERVATIVE_CALL_USD
    if pending and pending * conservative - 1e-9 > hard_cap_usd:
        raise RuntimeError(
            f"Cannot safely enforce ${hard_cap_usd:.2f} cap for {pending} unpaid stills "
            f"(reserve ${conservative:.2f}/call). STOP before generation."
        )
    if (pre.estimated_usd or 0) - 1e-9 > hard_cap_usd:
        raise RuntimeError(
            f"Estimated ${pre.estimated_usd} exceeds hard cap ${hard_cap_usd:.2f}; STOP"
        )

    for job in pre.jobs:
        dest = paths.custom_v2_scene_image(job.scene_id)
        meta = paths.custom_v2_scene_meta(job.scene_id)
        v1 = paths.scene_image_path(job.scene_id)
        if dest.resolve() == v1.resolve():
            raise RuntimeError("Refusing to overwrite V1 still")
        ref_hashes = _custom_ref_hashes(paths, job)
        existing = None
        if dest.is_file() and meta.is_file():
            try:
                loaded = load_model(meta, GeneratedImageManifest)
            except (OSError, ValueError):
                loaded = None
            else:
                if (
                    loaded.request_hash == job.request_hash
                    and loaded.generation_status == "success"
                ):
                    existing = loaded
        if existing is not None:
            local_hits += 1
            log(f"CACHE {job.scene_id}")
            continue
        cached = cache.get(CACHE_KIND, job.request_hash)
        if cached is not None:
            dest.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_bytes(dest, cached[0].read_bytes())
            digest = file_sha256(dest)
            _write_still_manifest(
                job=job,
                image_cfg=image_cfg,
                meta=meta,
                digest=digest,
                ref_hashes=ref_hashes,
                usage=cached[1].get("usage") if isinstance(cached[1].get("usage"), dict) else None,
                model=image_cfg.model,
                cache_hit=True,
            )
            recovered += 1
            _append_journal(
                paths,
                {
                    "scene_id": job.scene_id,
                    "state": "CACHE_COMMITTED",
                    "request_hash": job.request_hash,
                    "recovered": True,
                },
            )
            log(f"PAID_CACHE {job.scene_id}")
            continue
        if spent + conservative - 1e-9 > hard_cap_usd:
            stop_reason = f"Hard image cap ${hard_cap_usd:.2f} would be exceeded"
            raise RuntimeError(stop_reason)
        refs = [paths.root / rel for rel in job.references]
        attempted += 1
        _append_journal(
            paths,
            {
                "scene_id": job.scene_id,
                "state": "REQUEST_SUBMITTED",
                "request_hash": job.request_hash,
                "references": job.references,
                "reference_sha256": ref_hashes,
            },
        )
        try:
            result = adapter.generate(
                job.prompt,
                confirm_paid=True,
                seed=job.seed,
                reference_images=refs,
            )
        except Exception as exc:  # noqa: BLE001 — persist failure, do not retry aesthetically
            failures.append(f"{job.scene_id}:{exc}")
            _append_journal(
                paths,
                {
                    "scene_id": job.scene_id,
                    "state": "FAILED",
                    "request_hash": job.request_hash,
                    "error": str(exc),
                },
            )
            log(f"FAIL {job.scene_id} {exc}")
            continue
        paid += 1
        usage_cost = _cost_from_usage(result.usage)
        if usage_cost is None:
            dest.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_bytes(dest, result.image_bytes)
            digest = file_sha256(dest)
            _write_still_manifest(
                job=job,
                image_cfg=image_cfg,
                meta=meta,
                digest=digest,
                ref_hashes=ref_hashes,
                usage=result.usage,
                model=result.raw_model or image_cfg.model,
                cache_hit=False,
            )
            cache.put(
                CACHE_KIND,
                job.request_hash,
                result.image_bytes,
                suffix=dest.suffix,
                meta={"scene_id": job.scene_id, "kind": "custom_identity_still"},
            )
            stop_reason = "usage missing; cannot attribute further spend under $1 cap"
            _append_journal(
                paths,
                {
                    "scene_id": job.scene_id,
                    "state": "CACHE_COMMITTED",
                    "request_hash": job.request_hash,
                    "stop": stop_reason,
                },
            )
            raise RuntimeError(stop_reason)
        spent = round(spent + usage_cost, 6)
        dest.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(dest, result.image_bytes)
        digest = file_sha256(dest)
        _write_still_manifest(
            job=job,
            image_cfg=image_cfg,
            meta=meta,
            digest=digest,
            ref_hashes=ref_hashes,
            usage=result.usage,
            model=result.raw_model or image_cfg.model,
            cache_hit=False,
        )
        cache.put(
            CACHE_KIND,
            job.request_hash,
            result.image_bytes,
            suffix=dest.suffix,
            meta={"scene_id": job.scene_id, "kind": "custom_identity_still"},
        )
        _append_journal(
            paths,
            {
                "scene_id": job.scene_id,
                "state": "CACHE_COMMITTED",
                "request_hash": job.request_hash,
                "usage_usd": usage_cost,
                "spent_usd": spent,
            },
        )
        log(f"PAID {job.scene_id} spent={spent}")
        if spent - 1e-9 > hard_cap_usd:
            raise RuntimeError(f"Hard image cap ${hard_cap_usd:.2f} exceeded after {job.scene_id}")
    v1_after = {
        job.scene_id: file_sha256(paths.root / job.v1_still)
        for job in pre.jobs
        if (paths.root / job.v1_still).is_file()
    }
    return {
        "executed": True,
        "attempted": attempted,
        "paid_calls": paid,
        "cache_hits": local_hits,
        "recovered": recovered,
        "failures": failures,
        "spent_usd": spent,
        "remaining_usd": round(hard_cap_usd - spent, 6),
        "hard_cap_usd": hard_cap_usd,
        "stop_reason": stop_reason,
        "v1_modified": v1_before != v1_after,
        "generated": [
            job.scene_id
            for job in pre.jobs
            if paths.custom_v2_scene_image(job.scene_id).is_file()
        ],
        "missing": [
            job.scene_id
            for job in pre.jobs
            if not paths.custom_v2_scene_image(job.scene_id).is_file()
        ],
    }


def build_old_new_contact_sheet(paths: ProjectPaths, jobs: list[StillMigrationJob]) -> Path | None:
    entries: list[tuple[str, str, Path]] = []
    for job in jobs:
        old = paths.root / job.v1_still
        new = paths.root / job.output_path
        label = f"{job.scene_id} {job.beat_id}"
        if old.is_file():
            entries.append((label, "OLD", old))
        if new.is_file():
            entries.append((label, "NEW", new))
    dest = paths.review_dir / "custom_v2_character_contact_sheet.jpg"
    if not entries:
        return None
    return build_contact_sheet(paths, entries, columns=2, output=dest)


def qc_custom_still(paths: ProjectPaths, job: StillMigrationJob) -> list[str]:
    notes: list[str] = []
    dest = paths.root / job.output_path
    if not dest.is_file() or dest.stat().st_size == 0:
        return ["missing_or_empty"]
    v1 = paths.root / job.v1_still
    if v1.is_file() and file_sha256(dest) == file_sha256(v1):
        notes.append("duplicate_of_v1_hash")
    try:
        with Image.open(dest) as image:
            image.load()
            width, height = image.size
            extrema = image.convert("L").getextrema()
    except (OSError, ValueError):
        return ["corrupt"]
    if width < 16 or height < 16:
        notes.append("blank_or_tiny")
    if extrema[0] == extrema[1]:
        notes.append("blank_flat")
    if abs((width / height) - (16 / 9)) > 0.08:
        notes.append(f"not_16x9:{width}x{height}")
    if job.reference_count != len(job.characters):
        notes.append("reference_count_mismatch")
    meta = paths.custom_v2_scene_meta(job.scene_id)
    if not meta.is_file():
        notes.append("missing_meta")
        return notes
    loaded = load_model(meta, GeneratedImageManifest)
    if loaded.character_identity_versions != job.identity_versions:
        notes.append("identity_version_mismatch")
    if len(loaded.reference_paths) != job.reference_count:
        notes.append("submitted_ref_count_mismatch")
    if len(loaded.reference_sha256) != job.reference_count:
        notes.append("ref_hash_count_mismatch")
    notes.append("ok")
    return notes


def qc_migration_batch(paths: ProjectPaths, jobs: list[StillMigrationJob]) -> dict[str, Any]:
    per_scene = {job.scene_id: qc_custom_still(paths, job) for job in jobs}
    hashes = []
    for job in jobs:
        dest = paths.root / job.output_path
        if dest.is_file():
            hashes.append(file_sha256(dest))
    dupes = len(hashes) - len(set(hashes))
    payload = {
        "scenes": per_scene,
        "duplicate_new_outputs": dupes,
        "identity_ok": all("identity_version_mismatch" not in n for n in per_scene.values()),
    }
    save_json(paths.review_dir / "character_still_migration_qc.json", payload)
    return payload
