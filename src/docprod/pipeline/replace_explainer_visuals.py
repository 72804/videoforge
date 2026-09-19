from __future__ import annotations

import shutil
from dataclasses import asdict, dataclass
from pathlib import Path

from docprod.archive.models import ArchiveCandidate
from docprod.archive.scoring import score_archive_candidate
from docprod.archive.wikimedia import WikimediaCommonsProvider
from docprod.models.enums import AssetStrategy, VisualEffect
from docprod.models.project import Project
from docprod.models.scene import Scene, ScenePlan
from docprod.planning.visual_policy import (
    ARCHIVE_QUERIES,
    STOCK_QUERIES,
    VISUAL_POLICY,
    ReplacementItem,
    ReplacementReport,
    concept_for_scene,
    explicit_explainer_requested,
    still_prompt_for_concept,
)
from docprod.production import AssetPlan, AssetUnit, PhotoSequenceAsset
from docprod.production.balance import _apply_strategy
from docprod.production.info_graphics import is_named_person_scene
from docprod.providers.image_config import ImageGenerationConfig
from docprod.providers.openai_image import OpenAIImageProvider, image_request_hash
from docprod.providers.request_budget import ModelRequestBudget
from docprod.render.ffmpeg import probe_media
from docprod.stock.downloader import normalize_stock_clip, pick_clip_start
from docprod.stock.models import StockSourceManifest
from docprod.stock.scoring import pick_documentary_auto_candidate
from docprod.storage.hashing import file_sha256
from docprod.storage.json_store import atomic_write_bytes, load_model, save_json, save_model
from docprod.storage.paths import ProjectPaths

MAX_AI_BEFORE_STOP = 16
EST_IMAGE_USD = 0.01
EXISTING_STOCK_CONCEPTS: dict[str, str] = {
    "scene_0002": "warehouse_barrels",
    "scene_0007": "syrup_closeup",
    "scene_0010": "maple_harvesting",
    "scene_0013": "industrial_closeup",
    "scene_0015": "warehouse_barrels",
    "scene_0027": "warehouse_barrels",
    "scene_0031": "warehouse_barrels",
    "scene_0054": "anonymous_worker",
    "scene_0056": "storage_security",
    "scene_0058": "warehouse_barrels",
    "scene_0065": "empty_storage",
}

STILL_EFFECTS = (
    VisualEffect.slow_push_in,
    VisualEffect.slow_pull_out,
    VisualEffect.pan_left,
    VisualEffect.pan_right,
)


def is_generated_explainer_unit(unit: AssetUnit, scene: Scene) -> bool:
    if explicit_explainer_requested(scene):
        return False
    if unit.extra.get("document_kind") == "REAL_ARCHIVE_DOCUMENT":
        return False
    return unit.source_strategy in {
        AssetStrategy.generated_graphic,
        AssetStrategy.document,
        AssetStrategy.map,
        AssetStrategy.text_card,
    }


def scan_existing_library(paths: ProjectPaths) -> dict[str, list[Path]]:
    library: dict[str, list[Path]] = {key: [] for key in STOCK_QUERIES}
    stock_root = paths.artifacts_dir / "stock"
    if stock_root.is_dir():
        for scene_dir in sorted(stock_root.iterdir()):
            source = scene_dir / "source.mp4"
            if not source.is_file():
                continue
            concept = EXISTING_STOCK_CONCEPTS.get(scene_dir.name, "warehouse_barrels")
            library.setdefault(concept, []).append(source)
    archive_root = paths.artifacts_dir / "archive"
    if archive_root.is_dir():
        for unit_dir in sorted(archive_root.iterdir()):
            if not unit_dir.is_dir() or unit_dir.name == "candidates":
                continue
            for suffix in (".jpg", ".jpeg", ".png"):
                source = unit_dir / f"source{suffix}"
                if not source.is_file():
                    continue
                try:
                    from PIL import Image

                    Image.open(source).verify()
                except Exception:
                    continue
                library.setdefault("archive_evidence", []).append(source)
                break
    stills = paths.visuals_dir / "ai_stills"
    if stills.is_dir():
        for path in sorted(stills.glob("*.jpg")):
            library.setdefault("warehouse_barrels", []).append(path)
    return library


def plan_explainer_replacements(
    plan: ScenePlan,
    asset_plan: AssetPlan,
    *,
    library: dict[str, list[Path]] | None = None,
) -> ReplacementReport:
    scenes = {scene.id: scene for scene in plan.scenes}
    library = library or {}
    stock_used: dict[str, int] = {}
    archive_used: dict[str, int] = {}
    recent: list[str] = []
    items: list[ReplacementItem] = []
    for unit in asset_plan.units:
        first = scenes[unit.scene_ids[0]]
        if not is_generated_explainer_unit(unit, first):
            continue
        concept = concept_for_scene(first, recent)
        recent.append(concept)
        existing = [path for path in library.get(concept, []) if path.suffix.lower() == ".mp4"]
        archives = [
            path
            for path in library.get("archive_evidence", []) + library.get(concept, [])
            if path.suffix.lower() in {".jpg", ".jpeg", ".png"}
        ]
        photos = [path for path in library.get(concept, []) if path.suffix.lower() == ".jpg"]
        duration = float(unit.continuous_duration)
        sequence: list[str] = []
        if duration >= 8.0 and photos[:2]:
            sequence = [
                photos[0].as_posix(),
                (photos[1] if len(photos) > 1 else photos[0]).as_posix(),
            ]
        if existing:
            path = existing[stock_used.get(concept, 0) % len(existing)]
            stock_used[concept] = stock_used.get(concept, 0) + 1
            items.append(
                ReplacementItem(
                    unit_id=unit.asset_unit_id,
                    scene_ids=list(unit.scene_ids),
                    old_strategy=unit.source_strategy.value,
                    concept=concept,
                    source_type="existing_stock",
                    reuse_path=path.as_posix(),
                    sequence_paths=sequence,
                    duration=duration,
                )
            )
        elif archives and concept in {"archive_evidence"}:
            path = archives[archive_used.get(concept, 0) % len(archives)]
            archive_used[concept] = archive_used.get(concept, 0) + 1
            items.append(
                ReplacementItem(
                    unit_id=unit.asset_unit_id,
                    scene_ids=list(unit.scene_ids),
                    old_strategy=unit.source_strategy.value,
                    concept=concept,
                    source_type="archive",
                    query=(ARCHIVE_QUERIES.get(concept) or ("",))[0],
                    reuse_path=path.as_posix(),
                    duration=duration,
                )
            )
        elif photos:
            items.append(
                ReplacementItem(
                    unit_id=unit.asset_unit_id,
                    scene_ids=list(unit.scene_ids),
                    old_strategy=unit.source_strategy.value,
                    concept=concept,
                    source_type="reuse_photo",
                    reuse_path=photos[0].as_posix(),
                    sequence_paths=sequence,
                    duration=duration,
                )
            )
        elif concept in STOCK_QUERIES:
            items.append(
                ReplacementItem(
                    unit_id=unit.asset_unit_id,
                    scene_ids=list(unit.scene_ids),
                    old_strategy=unit.source_strategy.value,
                    concept=concept,
                    source_type="new_stock",
                    query=STOCK_QUERIES[concept][0],
                    duration=duration,
                )
            )
        else:
            items.append(
                ReplacementItem(
                    unit_id=unit.asset_unit_id,
                    scene_ids=list(unit.scene_ids),
                    old_strategy=unit.source_strategy.value,
                    concept=concept,
                    source_type="ai_still",
                    estimated_image_calls=1,
                    duration=duration,
                )
            )

    # Collapse identical new_stock/ai concepts so one search/image serves many units.
    by_concept: dict[str, list[ReplacementItem]] = {}
    for item in items:
        if item.source_type in {"new_stock", "ai_still"}:
            by_concept.setdefault(f"{item.source_type}:{item.concept}", []).append(item)
    for group in by_concept.values():
        if len(group) < 2:
            continue
        lead = group[0]
        for extra in group[1:]:
            extra.source_type = (
                "reuse_photo" if lead.source_type == "ai_still" else "existing_stock"
            )
            extra.estimated_image_calls = 0
            extra.query = lead.query

    existing_stock = sum(1 for item in items if item.source_type == "existing_stock")
    new_stock = sum(1 for item in items if item.source_type == "new_stock")
    archive = sum(1 for item in items if item.source_type == "archive")
    reuse = sum(1 for item in items if item.source_type == "reuse_photo")
    ai = sum(1 for item in items if item.source_type == "ai_still")
    image_calls = ai
    grouping_ok = image_calls <= MAX_AI_BEFORE_STOP
    scenes_affected = len({sid for item in items for sid in item.scene_ids})
    notes = [VISUAL_POLICY]
    if not grouping_ok:
        notes.append(f"STOP: {image_calls} AI stills exceeds grouping cap {MAX_AI_BEFORE_STOP}")
    return ReplacementReport(
        bad_units=items,
        existing_stock=existing_stock,
        new_stock=new_stock,
        archive=archive,
        reuse_photo=reuse,
        ai_stills=ai,
        image_calls=image_calls,
        affected_scenes=scenes_affected,
        estimated_cost_usd=round(image_calls * EST_IMAGE_USD, 4),
        grouping_ok=grouping_ok,
        notes=notes,
    )


def report_payload(report: ReplacementReport) -> dict:
    return {
        "policy": VISUAL_POLICY,
        "bad_units": len(report.bad_units),
        "affected_scenes": report.affected_scenes,
        "existing_stock": report.existing_stock,
        "new_stock": report.new_stock,
        "archive": report.archive,
        "reuse_photo": report.reuse_photo,
        "ai_stills": report.ai_stills,
        "image_calls": report.image_calls,
        "estimated_cost_usd": report.estimated_cost_usd,
        "grouping_ok": report.grouping_ok,
        "notes": report.notes,
        "units": [asdict(item) for item in report.bad_units],
    }


def apply_replacement_strategies(
    plan: ScenePlan, asset_plan: AssetPlan, report: ReplacementReport
) -> tuple[ScenePlan, AssetPlan]:
    scenes = {scene.id: scene for scene in plan.scenes}
    by_unit = {item.unit_id: item for item in report.bad_units}
    units: list[AssetUnit] = []
    effect_i = 0
    for unit in asset_plan.units:
        item = by_unit.get(unit.asset_unit_id)
        if item is None:
            units.append(unit)
            continue
        strategy = _strategy_for_source(item.source_type)
        extra = dict(unit.extra)
        extra["replacement_source"] = item.source_type
        extra["replacement_concept"] = item.concept
        extra["old_strategy"] = item.old_strategy
        if item.sequence_paths:
            extra["photo_sequence"] = PhotoSequenceAsset(stills=item.sequence_paths).model_dump()
        status = {
            "existing_stock": "READY_STOCK",
            "new_stock": "READY_STOCK",
            "archive": "READY_ARCHIVE",
            "reuse_photo": "READY_AI_IMAGE",
            "ai_still": "NEEDS_AI_IMAGE",
        }.get(item.source_type, "UNRESOLVED")
        units.append(
            unit.model_copy(
                update={
                    "source_strategy": strategy,
                    "status": status,  # type: ignore[arg-type]
                    "generation_required": item.source_type == "ai_still",
                    "source_path": item.reuse_path or unit.source_path,
                    "extra": extra,
                    "estimated_cost": "price unresolved" if item.source_type == "ai_still" else "0",
                }
            )
        )
        for index, scene_id in enumerate(unit.scene_ids):
            scene = scenes[scene_id]
            converted = _apply_strategy(scene, strategy, "visual_v2_cinematic")
            meta = dict(converted.metadata)
            meta["asset_unit_id"] = unit.asset_unit_id
            meta["replacement_concept"] = item.concept
            meta["old_visual_strategy"] = item.old_strategy
            if item.reuse_path:
                meta["source_path"] = item.reuse_path
            if item.sequence_paths:
                meta["photo_sequence"] = item.sequence_paths
                meta["photo_sequence_index"] = min(index, len(item.sequence_paths) - 1)
                if len(unit.scene_ids) == 1 and len(item.sequence_paths) >= 2:
                    meta["photo_sequence_split"] = "1"
            effect = STILL_EFFECTS[effect_i % len(STILL_EFFECTS)]
            if strategy is AssetStrategy.stock_video:
                effect = VisualEffect.none
            elif is_named_person_scene(scene):
                effect = VisualEffect.slow_push_in
            effect_i += 1
            scenes[scene_id] = converted.model_copy(
                update={"metadata": meta, "effect": effect, "asset_strategy": strategy}
            )
    ordered = [scenes[scene.id] for scene in plan.scenes]
    return (
        plan.model_copy(update={"scenes": ordered}),
        asset_plan.model_copy(update={"units": units, "asset_unit_count": len(units)}),
    )


def _strategy_for_source(source_type: str) -> AssetStrategy:
    if source_type in {"existing_stock", "new_stock"}:
        return AssetStrategy.stock_video
    if source_type == "archive":
        return AssetStrategy.archive_image
    return AssetStrategy.ai_image


def bind_stock_clip(
    paths: ProjectPaths, scene: Scene, source: Path, *, seed: int, duration: float
) -> str:
    dest_source = paths.stock_source_mp4(scene.id)
    dest_source.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() != dest_source.resolve():
        shutil.copy2(source, dest_source)
    start = pick_clip_start(
        source_duration=probe_media(dest_source).duration,
        needed=duration,
        seed=seed,
        scene_id=scene.id,
    )
    clip = paths.stock_clip_mp4(scene.id)
    sha = normalize_stock_clip(dest_source, clip, start=start, duration=duration)
    save_model(
        paths.stock_source_meta(scene.id),
        StockSourceManifest(
            scene_id=scene.id,
            provider="pexels",
            provider_video_id="reused",
            source_page_url="",
            creator_name="reused",
            duration=probe_media(dest_source).duration,
            width=1280,
            height=720,
            download_url="",
            downloaded_path=dest_source.relative_to(paths.root).as_posix(),
            sha256=file_sha256(dest_source),
            query="reuse-existing-stock",
            clip_start=start,
            clip_duration=duration,
            clip_path=clip.relative_to(paths.root).as_posix(),
            clip_sha256=sha,
        ),
    )
    return clip.relative_to(paths.root).as_posix()


def bind_still(paths: ProjectPaths, unit_id: str, source: Path, *, archive: bool) -> str:
    dest = (
        paths.archive_source_path(unit_id, ".jpg")
        if archive
        else paths.ai_unit_still_path(unit_id)
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    _write_preview_still(source, dest)
    return dest.relative_to(paths.root).as_posix()


def _write_preview_still(
    source: Path, dest: Path, *, max_w: int = 1920, max_h: int = 1080
) -> None:
    from PIL import Image, UnidentifiedImageError

    try:
        image = Image.open(source)
        image.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError(f"Not a raster image: {source}") from exc
    image = image.convert("RGB")
    image.thumbnail((max_w, max_h))
    image.save(dest, format="JPEG", quality=88, optimize=True)


@dataclass
class LiveReplacementResult:
    report: ReplacementReport
    plan: ScenePlan
    asset_plan: AssetPlan
    image_calls: int
    image_cost_usd: float | None
    cache_hits: int | None = None
    rendered_segments: int | None = None
    elapsed_s: float | None = None


def execute_free_replacements(
    paths: ProjectPaths,
    *,
    project: Project,
    plan: ScenePlan,
    asset_plan: AssetPlan,
    report: ReplacementReport,
    enable_pexels: bool,
    enable_commons: bool,
) -> tuple[ScenePlan, AssetPlan, ReplacementReport]:
    from docprod.pipeline.search_stock import search_stock, select_stock

    scenes = {scene.id: scene for scene in plan.scenes}
    searched_queries: dict[str, str] = {}
    commons = WikimediaCommonsProvider() if enable_commons else None
    for item in report.bad_units:
        first = scenes[item.scene_ids[0]]
        needed = sum(scenes[sid].duration for sid in item.scene_ids)
        if item.source_type == "existing_stock" and item.reuse_path:
            rel = bind_stock_clip(
                paths, first, Path(item.reuse_path), seed=project.random_seed, duration=needed
            )
            item.reuse_path = rel
            for extra_id in item.scene_ids[1:]:
                bind_stock_clip(
                    paths,
                    scenes[extra_id],
                    Path(item.reuse_path)
                    if (paths.root / item.reuse_path).is_file()
                    else Path(item.reuse_path),
                    seed=project.random_seed,
                    duration=scenes[extra_id].duration,
                )
        elif item.source_type == "new_stock" and enable_pexels:
            patched = first.model_copy(
                update={
                    "asset_strategy": AssetStrategy.stock_video,
                    "metadata": {
                        **first.metadata,
                        "stock_query_seed": item.query or item.concept,
                    },
                }
            )
            patched_plan = plan.model_copy(
                update={
                    "scenes": [patched if scene.id == first.id else scene for scene in plan.scenes]
                }
            )
            try:
                manifest = search_stock(
                    paths, project=project, plan=patched_plan, scene_id=first.id
                )
            except Exception as exc:  # noqa: BLE001
                item.source_type = "ai_still"
                item.estimated_image_calls = 1
                item.query = f"pexels_failed:{exc}"
                continue
            row = next((row for row in manifest.scenes if row.scene_id == first.id), None)
            best = pick_documentary_auto_candidate(row.candidates if row else [])
            if best is None:
                item.source_type = "ai_still"
                item.estimated_image_calls = 1
                continue
            selected = select_stock(
                paths,
                project=project,
                plan=patched_plan,
                scene_id=first.id,
                video_id=best.provider_video_id,
                selection_mode="documentary_auto",
            )
            item.reuse_path = selected.downloaded_path
            item.source_type = "existing_stock"
            searched_queries[item.concept] = selected.downloaded_path
        elif item.source_type == "new_stock" and item.concept in searched_queries:
            item.reuse_path = searched_queries[item.concept]
            item.source_type = "existing_stock"
        elif item.source_type == "archive" and item.reuse_path and Path(item.reuse_path).is_file():
            item.reuse_path = bind_still(paths, item.unit_id, Path(item.reuse_path), archive=True)
        elif item.source_type == "archive" and commons is not None:
            queries = ARCHIVE_QUERIES.get(item.concept) or (item.query,)
            ranked: list[ArchiveCandidate] = []
            for query in queries:
                try:
                    page = commons.search_files(query)
                except Exception:  # noqa: BLE001
                    continue
                for raw in page:
                    ranked.append(score_archive_candidate(raw, scene=first, query=query))
            ranked.sort(key=lambda cand: cand.score, reverse=True)
            if not ranked:
                item.source_type = "ai_still"
                item.estimated_image_calls = 1
                continue
            try:
                dest = paths.archive_source_path(item.unit_id, ".jpg")
                dest.parent.mkdir(parents=True, exist_ok=True)
                from docprod.archive.downloader import download_archive_file

                download_archive_file(commons, ranked[0].file_url, dest)
                item.reuse_path = dest.relative_to(paths.root).as_posix()
            except Exception:  # noqa: BLE001
                item.source_type = "ai_still"
                item.estimated_image_calls = 1
        elif item.source_type == "reuse_photo" and item.reuse_path:
            src = Path(item.reuse_path)
            if src.is_file():
                item.reuse_path = bind_still(paths, item.unit_id, src, archive=False)

    for item in report.bad_units:
        if item.reuse_path:
            continue
        shared = searched_queries.get(item.concept)
        if shared:
            src = Path(shared)
            if not src.is_file():
                src = paths.root / shared
            if src.is_file():
                first = scenes[item.scene_ids[0]]
                item.reuse_path = bind_stock_clip(
                    paths,
                    first,
                    src,
                    seed=project.random_seed,
                    duration=scenes[first.id].duration,
                )
                item.source_type = "existing_stock"
                continue
        if item.source_type in {"new_stock", "existing_stock"}:
            item.source_type = "ai_still"
            item.estimated_image_calls = 1

    # Recount AI after free-source fallbacks
    report.ai_stills = sum(1 for item in report.bad_units if item.source_type == "ai_still")
    report.image_calls = report.ai_stills
    report.existing_stock = sum(
        1 for item in report.bad_units if item.source_type == "existing_stock"
    )
    report.new_stock = sum(1 for item in report.bad_units if item.source_type == "new_stock")
    report.archive = sum(1 for item in report.bad_units if item.source_type == "archive")
    report.reuse_photo = sum(1 for item in report.bad_units if item.source_type == "reuse_photo")
    report.estimated_cost_usd = round(report.image_calls * EST_IMAGE_USD, 4)
    report.grouping_ok = report.image_calls <= MAX_AI_BEFORE_STOP
    return plan, asset_plan, report


def generate_replacement_stills(
    paths: ProjectPaths,
    *,
    project: Project,
    plan: ScenePlan,
    report: ReplacementReport,
    confirm_paid: bool,
    budget: ModelRequestBudget,
) -> float:
    scenes = {scene.id: scene for scene in plan.scenes}
    config = ImageGenerationConfig.from_settings()
    provider = OpenAIImageProvider(config=config)
    total_cost = 0.0
    for item in report.bad_units:
        if item.source_type != "ai_still":
            continue
        scene = scenes[item.scene_ids[0]]
        if is_named_person_scene(scene):
            prompt = still_prompt_for_concept("courthouse", scene)
        else:
            prompt = still_prompt_for_concept(item.concept, scene)
        request_hash = image_request_hash(
            prompt=prompt,
            config=config,
            seed=project.random_seed,
            extra={"asset_unit_id": item.unit_id, "kind": "visual_v2_still"},
        )
        output = paths.ai_unit_still_path(item.unit_id)
        meta = paths.ai_unit_still_meta(item.unit_id)
        if meta.is_file() and output.is_file():
            item.reuse_path = output.relative_to(paths.root).as_posix()
            continue
        budget.reserve("image")
        result = provider.generate(
            prompt, confirm_paid=confirm_paid, seed=project.random_seed, max_attempts=1
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(output, result.image_bytes)
        digest = file_sha256(output)
        rel = output.relative_to(paths.root).as_posix()
        from docprod.providers.image_config import GeneratedImageManifest

        save_model(
            meta,
            GeneratedImageManifest(
                provider=config.provider,
                model=result.raw_model or config.model,
                scene_id=item.unit_id,
                prompt=prompt,
                size=config.size,
                quality=config.quality,
                output_format=config.output_format,
                seed_requested=project.random_seed,
                source_scene_hash=request_hash,
                request_hash=request_hash,
                output_path=rel,
                output_sha256=digest,
                revised_prompt=result.revised_prompt,
                usage=result.usage,
                generation_status="success",
                cache_hit=False,
                elapsed_seconds=round(result.elapsed_seconds, 3),
            ),
        )
        item.reuse_path = rel
        if result.usage:
            total_cost += _image_cost(result.usage)
    return round(total_cost, 6)


def _image_cost(usage: dict) -> float:
    text_in = usage.get("input_tokens") or usage.get("text_tokens") or 0
    image_out = usage.get("output_tokens") or 0
    details = usage.get("input_tokens_details") or {}
    image_in = details.get("image_tokens") or 0 if isinstance(details, dict) else 0
    return (
        float(text_in) * 5 / 1_000_000
        + float(image_in) * 8 / 1_000_000
        + float(image_out) * 30 / 1_000_000
    )


def write_replacement_contact_sheet(
    paths: ProjectPaths, report: ReplacementReport, plan: ScenePlan
) -> Path | None:
    from PIL import Image, ImageDraw

    from docprod.graphics.fonts import discover_sans_font, load_font

    tile_w, tile_h, label_h = 320, 180, 54
    cols = 2
    rows = len(report.bad_units)
    if rows == 0:
        return None
    sheet = Image.new("RGB", (cols * tile_w, rows * (tile_h + label_h)), (10, 10, 12))
    draw = ImageDraw.Draw(sheet)
    font = load_font(discover_sans_font(), 13)
    scenes = {scene.id: scene for scene in plan.scenes}
    for index, item in enumerate(report.bad_units):
        y = index * (tile_h + label_h)
        old = paths.scene_graphic_png(item.scene_ids[0])
        if not old.is_file():
            old = paths.scene_map_base(item.scene_ids[0])
        new = Path(item.reuse_path or "")
        if not new.is_file():
            new = paths.root / (item.reuse_path or "")
        if not new.is_file():
            new = paths.ai_unit_still_path(item.unit_id)
        for col, path in enumerate((old, new)):
            x = col * tile_w
            if path.is_file():
                try:
                    image = Image.open(path).convert("RGB")
                    image.thumbnail((tile_w, tile_h))
                    sheet.paste(image, (x + (tile_w - image.width) // 2, y))
                except OSError:
                    pass
        label = (
            f"{item.unit_id} {','.join(item.scene_ids)} "
            f"{item.old_strategy}->{item.source_type}/{item.concept}"
        )
        draw.text((8, y + tile_h + 8), label[:80], fill=(230, 230, 230), font=font)
        _ = scenes
    dest = paths.visual_replacement_contact_sheet()
    dest.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(dest, quality=88)
    return dest


def runtime_visual_fractions(plan: ScenePlan) -> dict[str, float]:
    total = sum(scene.duration for scene in plan.scenes) or 1.0

    def frac(pred) -> float:
        return round(sum(scene.duration for scene in plan.scenes if pred(scene)) / total, 4)

    return {
        "photographic": frac(
            lambda s: (
                s.asset_strategy
                in {
                    AssetStrategy.ai_image,
                    AssetStrategy.archive_image,
                    AssetStrategy.ai_image_to_video,
                }
            )
        ),
        "native_video": frac(
            lambda s: s.asset_strategy in {AssetStrategy.stock_video, AssetStrategy.archive_video}
        ),
        "archive": frac(
            lambda s: s.asset_strategy in {AssetStrategy.archive_image, AssetStrategy.archive_video}
        ),
        "information_graphic": frac(
            lambda s: (
                s.asset_strategy
                in {
                    AssetStrategy.generated_graphic,
                    AssetStrategy.document,
                    AssetStrategy.map,
                    AssetStrategy.text_card,
                }
                and not explicit_explainer_requested(s)
            )
        ),
    }


def save_replacement_plan(paths: ProjectPaths, report: ReplacementReport) -> None:
    save_json(paths.visual_replacement_plan_json(), report_payload(report))


def render_visual_v2(
    paths: ProjectPaths,
    *,
    project: Project,
    plan: ScenePlan,
    asset_plan: AssetPlan,
) -> tuple[int, int, float]:
    from time import perf_counter

    from docprod.audio.models import AlignmentReport, RuntimeTimeline
    from docprod.audio.timeline import apply_runtime_timeline
    from docprod.pipeline.inspect_assets import require_zero_placeholders
    from docprod.pipeline.render_review_episode import _stamp_unit_progress, retime_stock_units
    from docprod.render.models import PreviewRenderProfile
    from docprod.render.renderer import render_preview

    timeline = load_model(paths.runtime_timeline_json(), RuntimeTimeline)
    runtime = apply_runtime_timeline(plan, timeline)
    runtime = _stamp_unit_progress(runtime, asset_plan)
    retime_stock_units(paths, plan=runtime, asset_plan=asset_plan, seed=project.random_seed)
    require_zero_placeholders(paths, runtime)
    alignment = None
    if paths.narration_alignment_json().is_file():
        alignment = load_model(paths.narration_alignment_json(), AlignmentReport)
    started = perf_counter()
    result = render_preview(
        paths,
        project=project,
        plan=runtime,
        profile=PreviewRenderProfile(segment_workers=4),
        workers=4,
        use_cache=True,
        output_mp4=paths.preview_visual_v2_mp4(),
        manifest_path=paths.preview_visual_v2_manifest(),
        captions_srt=paths.captions_narrated_srt(),
        captions_ass=paths.captions_narrated_ass(),
        narration_wav=paths.narration_master_wav(),
        allow_placeholders=False,
        alignment=alignment,
        write_caption_files=False,
    )
    return result.cache_hits, result.rendered_segments, perf_counter() - started
