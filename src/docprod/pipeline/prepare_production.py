from __future__ import annotations

from dataclasses import dataclass

from docprod.archive.contact import build_archive_contact_sheet
from docprod.archive.downloader import download_archive_file
from docprod.archive.manifest import credit_from_candidate, record_archive_credit
from docprod.archive.models import ArchiveCandidate
from docprod.archive.query import archive_queries
from docprod.archive.scoring import score_archive_candidate
from docprod.archive.wikimedia import WikimediaCommonsProvider
from docprod.config import Settings, get_settings
from docprod.exceptions import ArchiveProviderError, MissingApiKeyError, StockProviderError
from docprod.graphics.renderer import execute_generate_graphic
from docprod.models.enums import AssetStrategy
from docprod.models.project import Project
from docprod.models.scene import Scene, ScenePlan
from docprod.pipeline.search_stock import search_stock, select_stock
from docprod.production import AIStillSpec, AIVideoSpec, AssetPlan, AssetUnit
from docprod.production.balance import rebalance_scene_plan
from docprod.production.cost import build_cost_preview
from docprod.production.grouping import group_asset_units, saved_generation_count
from docprod.production.prompts import (
    NEGATIVE,
    fallback_strategy,
    historical_constraints,
    still_prompt_for,
    video_motion_for,
)
from docprod.stock.scoring import pick_documentary_auto_candidate
from docprod.storage.json_store import atomic_write_text, save_json, save_model
from docprod.storage.paths import ProjectPaths
from docprod.writing.models import NarrationScript


@dataclass
class PrepareResult:
    plan: ScenePlan
    asset_plan: AssetPlan
    review_items: list[str]


def prepare_production(
    paths: ProjectPaths,
    *,
    project: Project,
    plan: ScenePlan,
    script: NarrationScript | None = None,
    settings: Settings | None = None,
    commons: WikimediaCommonsProvider | None = None,
    enable_pexels: bool = True,
    enable_commons: bool = True,
    enable_local_graphics: bool = True,
) -> PrepareResult:
    _ = settings or get_settings()
    balanced = rebalance_scene_plan(plan)
    save_model(paths.scene_plan_json, balanced)
    units = group_asset_units(balanced)
    saved = saved_generation_count(balanced, units)
    scene_by_id = {scene.id: scene for scene in balanced.scenes}
    resolved: list[AssetUnit] = []
    review: list[str] = []
    commons_client = commons or WikimediaCommonsProvider()
    stock_searched = False
    used_archive_titles: set[str] = set()
    for unit in units:
        scene = scene_by_id[unit.scene_ids[0]]
        if unit.source_strategy in {
            AssetStrategy.generated_graphic,
            AssetStrategy.document,
            AssetStrategy.map,
            AssetStrategy.text_card,
        }:
            resolved.append(
                _resolve_local(paths, project, scene, unit, enable=enable_local_graphics)
            )
        elif unit.source_strategy is AssetStrategy.stock_video:
            if enable_pexels and not stock_searched:
                try:
                    search_stock(paths, project=project, plan=balanced)
                except (MissingApiKeyError, StockProviderError) as exc:
                    review.append(f"Pexels search skipped ({exc})")
                stock_searched = True
            resolved.append(
                _resolve_stock(
                    paths,
                    project,
                    balanced,
                    scene,
                    unit,
                    enable=enable_pexels,
                    review=review,
                    search_already_ran=stock_searched,
                )
            )
        elif unit.source_strategy in {
            AssetStrategy.archive_image,
            AssetStrategy.archive_video,
        }:
            resolved.append(
                _resolve_archive(
                    paths,
                    project,
                    scene,
                    unit,
                    commons_client,
                    enable=enable_commons,
                    review=review,
                    scene_by_id=scene_by_id,
                    used_titles=used_archive_titles,
                )
            )
        elif unit.source_strategy is AssetStrategy.ai_image:
            resolved.append(_write_still_spec(paths, scene, unit, scene_by_id))
        elif unit.source_strategy is AssetStrategy.ai_image_to_video:
            resolved.append(_write_video_spec(paths, scene, unit, scene_by_id))
        else:
            resolved.append(unit.model_copy(update={"status": "UNRESOLVED"}))
    asset_plan = AssetPlan(
        project_id=project.id,
        scene_count=len(balanced.scenes),
        asset_unit_count=len(resolved),
        saved_generation_count=saved,
        units=resolved,
    )
    cost = build_cost_preview(
        project_id=project.id, plan=balanced, asset_plan=asset_plan, script=script
    )
    asset_plan = asset_plan.model_copy(update={"cost": cost})
    save_model(paths.asset_plan_json(), asset_plan)
    review_text = _write_review_queue(paths, resolved, review)
    _ = review_text
    return PrepareResult(plan=balanced, asset_plan=asset_plan, review_items=review)


def _resolve_local(
    paths: ProjectPaths,
    project: Project,
    scene: Scene,
    unit: AssetUnit,
    *,
    enable: bool,
) -> AssetUnit:
    if not enable:
        return unit.model_copy(update={"status": "READY_LOCAL", "provider": "local"})
    manifest = execute_generate_graphic(paths, scene=scene, seed=project.random_seed)
    return unit.model_copy(
        update={
            "status": "READY_LOCAL",
            "provider": "local",
            "source": manifest.graphic_type,
            "source_path": manifest.output_path,
            "estimated_cost": "0",
        }
    )


def _resolve_stock(
    paths: ProjectPaths,
    project: Project,
    plan: ScenePlan,
    scene: Scene,
    unit: AssetUnit,
    *,
    enable: bool,
    review: list[str],
    search_already_ran: bool = False,
) -> AssetUnit:
    if not enable:
        return _fallback_ai_still(paths, scene, unit, "stock disabled")
    try:
        if not search_already_ran:
            search_stock(paths, project=project, plan=plan, scene_id=scene.id)
        from docprod.stock.models import StockSearchManifest
        from docprod.storage.json_store import load_model

        manifest = load_model(paths.stock_candidates_json(), StockSearchManifest)
        row = next((item for item in manifest.scenes if item.scene_id == scene.id), None)
        candidates = row.candidates if row else []
        best = pick_documentary_auto_candidate(candidates)
        if best is None:
            review.append(f"{unit.asset_unit_id}: weak Pexels match → AI still fallback")
            return _fallback_ai_still(paths, scene, unit, "weak stock match")
        selected = select_stock(
            paths,
            project=project,
            plan=plan,
            scene_id=scene.id,
            video_id=best.provider_video_id,
            selection_mode="documentary_auto",
        )
        return unit.model_copy(
            update={
                "status": "READY_STOCK",
                "provider": "pexels",
                "source": selected.provider_video_id,
                "source_path": selected.downloaded_path,
                "credit_id": selected.provider_video_id,
                "estimated_cost": "0",
                "extra": {"score_reasons": best.score_reasons},
            }
        )
    except (MissingApiKeyError, StockProviderError, OSError, ValueError) as exc:
        review.append(f"{unit.asset_unit_id}: Pexels unavailable ({exc}) → AI still fallback")
        return _fallback_ai_still(paths, scene, unit, str(exc))


def _resolve_archive(
    paths: ProjectPaths,
    project: Project,
    scene: Scene,
    unit: AssetUnit,
    client: WikimediaCommonsProvider,
    *,
    enable: bool,
    review: list[str],
    scene_by_id: dict[str, Scene],
    used_titles: set[str],
) -> AssetUnit:
    if not enable:
        return _archive_fallback(paths, project, scene, unit, "commons disabled", review)
    queries = archive_queries(scene)
    unique: dict[str, ArchiveCandidate] = {}
    try:
        for query in queries:
            for candidate in client.search_files(query, limit=8):
                scored = score_archive_candidate(candidate, scene=scene, query=query)
                prior = unique.get(scored.title)
                if prior is None or scored.score > prior.score:
                    unique[scored.title] = scored
    except ArchiveProviderError as exc:
        return _archive_fallback(paths, project, scene, unit, str(exc), review)
    ranked = sorted(unique.values(), key=lambda item: item.score, reverse=True)[:16]
    save_json(
        paths.archive_candidates_json(),
        {
            "asset_unit_id": unit.asset_unit_id,
            "candidates": [item.model_dump() for item in ranked],
        },
    )
    auto = [
        item
        for item in ranked
        if item.decision == "AUTO_REUSABLE"
        and item.file_url
        and item.score >= 40
        and item.title not in used_titles
        and (
            item.mime.startswith("image/")
            or item.media_type in {"BITMAP", "VIDEO"}
        )
    ]
    sheet = None
    if auto:
        chosen = auto[0]
        suffix = ".jpg"
        if "png" in (chosen.mime or chosen.file_url).lower():
            suffix = ".png"
        dest = paths.archive_source_path(unit.asset_unit_id, suffix)
        try:
            digest = download_archive_file(client, chosen.file_url, dest)
        except ArchiveProviderError as exc:
            return _archive_fallback(paths, project, scene, unit, str(exc), review)
        rel = dest.relative_to(paths.root).as_posix()
        record = credit_from_candidate(unit.asset_unit_id, chosen, rel, digest)
        record_archive_credit(paths, project.id, record)
        save_model(paths.archive_source_meta(unit.asset_unit_id), record)
        used_titles.add(chosen.title)
        return unit.model_copy(
            update={
                "status": "READY_ARCHIVE",
                "provider": "wikimedia_commons",
                "source": chosen.title,
                "source_path": rel,
                "credit_id": chosen.title,
                "estimated_cost": "0",
                "extra": {
                    "sheet": str(sheet) if sheet else "",
                    "license": chosen.license_short_name,
                },
            }
        )
    sheet = build_archive_contact_sheet(
        ranked,
        paths.archive_candidates_sheet(unit.asset_unit_id),
        fetch_bytes=client.fetch_bytes,
    )
    if ranked and ranked[0].decision == "REVIEW_REQUIRED":
        review.append(
            f"{unit.asset_unit_id}: Commons license/fit review ({ranked[0].title})"
        )
        return unit.model_copy(
            update={
                "status": "REVIEW_REQUIRED",
                "provider": "wikimedia_commons",
                "warnings": [ranked[0].decision_reason],
                "extra": {"sheet": str(sheet) if sheet else ""},
            }
        )
    return _archive_fallback(paths, project, scene, unit, "no confident Commons match", review)


def _archive_fallback(
    paths: ProjectPaths,
    project: Project,
    scene: Scene,
    unit: AssetUnit,
    reason: str,
    review: list[str],
) -> AssetUnit:
    alt = fallback_strategy(scene)
    review.append(f"{unit.asset_unit_id}: archive fallback ({reason}) → {alt.value}")
    if alt is AssetStrategy.document:
        doc_scene = scene.model_copy(update={"asset_strategy": AssetStrategy.document})
        graphic = execute_generate_graphic(paths, scene=doc_scene, seed=project.random_seed)
        return unit.model_copy(
            update={
                "status": "READY_LOCAL",
                "provider": "local",
                "source_strategy": AssetStrategy.document,
                "source_path": graphic.output_path,
                "warnings": [reason],
                "estimated_cost": "0",
            }
        )
    return _fallback_ai_still(paths, scene, unit, reason)


def _fallback_ai_still(
    paths: ProjectPaths, scene: Scene, unit: AssetUnit, reason: str
) -> AssetUnit:
    updated = unit.model_copy(
        update={
            "source_strategy": AssetStrategy.ai_image,
            "generation_required": True,
            "warnings": [reason],
        }
    )
    return _write_still_spec(paths, scene, updated, {scene.id: scene})


def _write_still_spec(
    paths: ProjectPaths,
    scene: Scene,
    unit: AssetUnit,
    scene_by_id: dict[str, Scene],
) -> AssetUnit:
    first = scene_by_id[unit.scene_ids[0]]
    spec = AIStillSpec(
        asset_unit_id=unit.asset_unit_id,
        scene_ids=unit.scene_ids,
        duration_needed=unit.continuous_duration,
        prompt=still_prompt_for(first),
        negative_constraints=list(NEGATIVE),
        historical_constraints=historical_constraints(first),
        continuity_refs=list(first.metadata.get("continuity_entities") or []),
        estimated_requests=1,
    )
    path = paths.ai_still_spec_path(unit.asset_unit_id)
    save_model(path, spec)
    return unit.model_copy(
        update={
            "status": "NEEDS_AI_IMAGE",
            "generation_required": True,
            "generation_spec_path": path.relative_to(paths.root).as_posix(),
            "estimated_cost": "price unresolved",
        }
    )


def _write_video_spec(
    paths: ProjectPaths,
    scene: Scene,
    unit: AssetUnit,
    scene_by_id: dict[str, Scene],
) -> AssetUnit:
    first = scene_by_id[unit.scene_ids[0]]
    spec = AIVideoSpec(
        asset_unit_id=unit.asset_unit_id,
        scene_ids=unit.scene_ids,
        duration_needed=unit.continuous_duration,
        motion_description=video_motion_for(first),
        historical_constraints=historical_constraints(first),
        estimated_requests=1,
    )
    path = paths.ai_video_spec_path(unit.asset_unit_id)
    save_model(path, spec)
    return unit.model_copy(
        update={
            "status": "NEEDS_AI_VIDEO",
            "generation_required": True,
            "generation_spec_path": path.relative_to(paths.root).as_posix(),
            "estimated_cost": "price unresolved",
        }
    )


def _write_review_queue(paths: ProjectPaths, units: list[AssetUnit], extra: list[str]) -> str:
    lines = ["# Asset review queue", ""]
    items = extra[:]
    for unit in units:
        if unit.status in {"REVIEW_REQUIRED", "UNRESOLVED"}:
            items.append(f"{unit.asset_unit_id} {unit.status}: {unit.visual_concept}")
    if not items:
        lines.append("No items require human review.")
    else:
        for item in items[:30]:
            lines.append(f"- {item}")
    text = "\n".join(lines).rstrip() + "\n"
    atomic_write_text(paths.asset_review_queue_md(), text)
    return text
