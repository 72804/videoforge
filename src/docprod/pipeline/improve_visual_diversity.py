from __future__ import annotations

import hashlib
import json
import shutil
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

from docprod.archive.downloader import download_archive_file
from docprod.archive.models import ArchiveCandidate, ArchiveSourceManifest
from docprod.archive.scoring import score_archive_candidate
from docprod.archive.wikimedia import WikimediaCommonsProvider
from docprod.models.enums import AssetStrategy, VisualEffect
from docprod.models.project import Project
from docprod.models.scene import Scene, ScenePlan
from docprod.planning.visual_diversity import (
    COURT_QUERIES,
    FAMILY_NEGATIVE,
    FAMILY_POSITIVE,
    MAPLE_VARIETY_QUERIES,
    POLICE_FAMILIES,
    REUSE_NEARBY_SECONDS,
    REUSE_NEARBY_WARN,
    REUSE_TOTAL_WARN,
    SCC_QUERIES,
    WAREHOUSE_FAMILIES,
    DiversityItem,
    DiversityReport,
    collect_source_uses,
    court_warehouse_mismatch,
    detect_repetition,
    family_from_query,
    file_fingerprint,
    metrics_from_uses,
    resolve_unit_media,
    visual_need,
)
from docprod.planning.visual_policy import EXPLAINER_STRATEGIES
from docprod.production import AssetPlan, AssetUnit, PhotoSequenceAsset
from docprod.production.balance import _apply_strategy
from docprod.render.ffmpeg import probe_media, run_ffmpeg
from docprod.stock.downloader import download_file, normalize_stock_clip, pick_clip_start
from docprod.stock.models import StockSourceManifest, StockVideoCandidate
from docprod.stock.pexels import PexelsStockVideoProvider
from docprod.stock.scoring import choose_rendition, score_candidate
from docprod.storage.hashing import file_sha256
from docprod.storage.json_store import load_model, save_model
from docprod.storage.paths import ProjectPaths

STILL_EFFECTS = (
    VisualEffect.slow_push_in,
    VisualEffect.slow_pull_out,
    VisualEffect.pan_left,
    VisualEffect.pan_right,
)
MAX_QUERY_VARIANTS = 3
PER_PAGE = 20


@dataclass
class DiversityLiveStats:
    new_stock_downloads: int = 0
    new_archive_downloads: int = 0
    paid_api_calls: int = 0
    cache_hits: int | None = None
    rendered: int | None = None
    elapsed_s: float | None = None


def _stock_query(paths: ProjectPaths, scene_id: str) -> str:
    meta = paths.stock_source_meta(scene_id)
    if not meta.is_file():
        return ""
    try:
        payload = json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    return str(payload.get("query") or "")


def _visual_family(paths: ProjectPaths, unit: AssetUnit, scene: Scene, path: Path | None) -> str:
    query = _stock_query(paths, scene.id)
    return family_from_query(query, path.as_posix() if path else "")


def index_existing_stock(paths: ProjectPaths) -> dict[str, list[Path]]:
    library: dict[str, list[Path]] = {}
    seen: set[str] = set()
    stock_root = paths.artifacts_dir / "stock"
    if not stock_root.is_dir():
        return library
    for scene_dir in sorted(stock_root.iterdir()):
        source = scene_dir / "source.mp4"
        if not source.is_file():
            continue
        digest = file_fingerprint(source)
        if digest in seen:
            continue
        seen.add(digest)
        query = _stock_query(paths, scene_dir.name)
        family = family_from_query(query, source.as_posix())
        library.setdefault(family, []).append(source)
        library.setdefault(digest, []).append(source)
    return library


def plan_diversity_replacements(
    paths: ProjectPaths, plan: ScenePlan, asset_plan: AssetPlan
) -> DiversityReport:
    uses = collect_source_uses(paths, plan, asset_plan)
    warnings = detect_repetition(uses)
    metrics = metrics_from_uses(uses, warnings)
    scenes = {scene.id: scene for scene in plan.scenes}
    use_by_unit = {item.unit_id: item for item in uses}
    counts = Counter(item.source_id for item in uses if item.source_id != "missing")
    police_counts: Counter[str] = Counter()
    warehouse_seen: dict[str, list[float]] = {}
    items: list[DiversityItem] = []
    motif_marked: set[str] = set()

    barrel_ids = [
        item.source_id
        for item in uses
        if family_from_query(_stock_query(paths, item.scene_ids[0]), item.path)
        in WAREHOUSE_FAMILIES.union({"warehouse_barrels"})
    ]
    barrel_top = Counter(barrel_ids).most_common(1)
    barrel_source = barrel_top[0][0] if barrel_top else ""
    barrel_units = [item for item in uses if item.source_id == barrel_source]
    if len(barrel_units) >= 2:
        motif_marked.add(barrel_units[0].unit_id)
        motif_marked.add(barrel_units[-1].unit_id)

    police_overused = {
        source_id
        for source_id, total in Counter(
            item.source_id
            for item in uses
            if item.visual_need in POLICE_FAMILIES and item.source_id != "missing"
        ).items()
        if total > 2
    }

    court_mismatch = 0
    for unit in asset_plan.units:
        first = scenes[unit.scene_ids[0]]
        use = use_by_unit[unit.asset_unit_id]
        if unit.source_strategy in EXPLAINER_STRATEGIES:
            continue
        if unit.source_strategy in {
            AssetStrategy.ai_image,
            AssetStrategy.ai_image_to_video,
            AssetStrategy.archive_image,
            AssetStrategy.archive_video,
        }:
            continue
        media = resolve_unit_media(paths, unit, first)
        family = _visual_family(paths, unit, first, media)
        need = visual_need(first)
        snippet = first.narration[:120]
        mismatch = court_warehouse_mismatch(first, family) or (
            need in {"court", "scc"}
            and family in WAREHOUSE_FAMILIES.union({"warehouse_barrels", "police", "maple_forest"})
        )
        if mismatch:
            court_mismatch += 1
        police_need = need in POLICE_FAMILIES
        if police_need:
            police_counts[use.source_id] += 1

        action = None
        reason = ""
        priority = "P5"
        target_family = need
        queries: tuple[str, ...] = ()

        if police_need and (counts[use.source_id] > 2 or use.source_id in police_overused):
            action = "new_stock"
            reason = "police_source_duplicated"
            priority = "P1"
            queries = POLICE_FAMILIES[need]
        elif use.source_id in police_overused and not police_need:
            action = "existing_stock"
            reason = "police_clip_on_nonpolice_beat"
            priority = "P1"
            queries = MAPLE_VARIETY_QUERIES.get(need) or POLICE_FAMILIES.get(
                "warehouse_search", ()
            )
        elif mismatch:
            action = "archive" if need == "scc" else "new_stock"
            reason = "court_warehouse_mismatch"
            priority = "P2"
            queries = SCC_QUERIES if need == "scc" else COURT_QUERIES
            target_family = need
        elif need == "scc":
            action = "archive"
            reason = "supreme_court_archive"
            priority = "P2"
            queries = SCC_QUERIES
            target_family = "scc"
        elif (
            family in WAREHOUSE_FAMILIES.union({"warehouse_barrels"})
            and counts[use.source_id] > REUSE_TOTAL_WARN
            and unit.asset_unit_id not in motif_marked
            and need not in {"court", "scc"}
            and not police_need
        ):
            nearby = warehouse_seen.setdefault(use.source_id, [])
            nearby_hits = sum(
                1 for start in nearby if abs(start - use.start) <= REUSE_NEARBY_SECONDS
            )
            nearby.append(use.start)
            if nearby_hits >= REUSE_NEARBY_WARN or counts[use.source_id] > REUSE_TOTAL_WARN:
                action = "existing_stock"
                reason = "warehouse_barrel_repetition"
                priority = "P3"
                target_family = need if need in MAPLE_VARIETY_QUERIES else "quebec_countryside"
                queries = MAPLE_VARIETY_QUERIES.get(target_family) or MAPLE_VARIETY_QUERIES[
                    "quebec_countryside"
                ]
        elif (
            float(unit.continuous_duration) >= 8.0
            and unit.source_strategy
            in {AssetStrategy.archive_image, AssetStrategy.ai_image}
            and not (first.metadata.get("photo_sequence") or [])
        ):
            action = "photo_sequence"
            reason = "long_still_span"
            priority = "P4"
            target_family = need

        if action is None:
            continue
        items.append(
            DiversityItem(
                unit_id=unit.asset_unit_id,
                scene_ids=list(unit.scene_ids),
                reason=reason,
                family=target_family,
                action=action,
                query=queries[0] if queries else target_family,
                old_source_id=use.source_id,
                narration_snippet=snippet,
                priority=priority,
            )
        )

    notes = [
        "Prefer photographic/filmic visual storytelling over explanatory generated graphics.",
        "Free sources only: Pexels and Wikimedia Commons.",
        f"Reuse warning: >{REUSE_TOTAL_WARN} total or >{REUSE_NEARBY_WARN} within "
        f"{int(REUSE_NEARBY_SECONDS)}s unless continuity flags.",
    ]
    return DiversityReport(
        uses=uses,
        warnings=warnings,
        items=items,
        unique_sources=metrics["unique_sources"],
        max_reuse=metrics["max_reuse"],
        sources_reused_over_2=metrics["sources_reused_over_2"],
        nearby_warnings=metrics["nearby_warnings"],
        police_duplicate_max=metrics["police_duplicate_max"],
        court_mismatch=court_mismatch,
        paid_api_calls=0,
        notes=notes,
    )


def report_payload(report: DiversityReport) -> dict:
    return {
        "unique_sources": report.unique_sources,
        "max_reuse": report.max_reuse,
        "sources_reused_over_2": report.sources_reused_over_2,
        "nearby_warnings": report.nearby_warnings,
        "police_duplicate_max": report.police_duplicate_max,
        "court_mismatch": report.court_mismatch,
        "items": len(report.items),
        "paid_api_calls": report.paid_api_calls,
        "warnings": [asdict(item) for item in report.warnings],
        "changes": [asdict(item) for item in report.items],
        "notes": report.notes,
    }


def _search_cache_path(paths: ProjectPaths, query: str) -> Path:
    digest = hashlib.sha1(query.encode("utf-8")).hexdigest()[:16]
    paths.stock_candidates_dir.mkdir(parents=True, exist_ok=True)
    return paths.stock_candidates_dir / f"diversity_query_{digest}.json"


def _family_score(candidate: StockVideoCandidate, family: str) -> float:
    hay = " ".join(
        [candidate.source_page_url, str(candidate.extra.get("title") or ""), candidate.query]
    ).casefold()
    score = float(candidate.score)
    for token in FAMILY_POSITIVE.get(family, ()):
        if token in hay:
            score += 12
    for token in FAMILY_NEGATIVE.get(family, ()):
        if token in hay:
            score -= 30
    if candidate.rejected and candidate.reject_reason and "highway" in (
        candidate.reject_reason or ""
    ):
        if family in {"police_vehicle", "truck_transport", "rural_road"}:
            score += 20
    return score


def _usable(candidate: StockVideoCandidate, family: str) -> bool:
    if candidate.rejected:
        if family in {"police_vehicle", "truck_transport", "rural_road"} and (
            candidate.reject_reason or ""
        ).startswith("rejected_concept:highway"):
            return candidate.duration >= 6.0 and candidate.width >= 1280
        return False
    hay = " ".join([candidate.source_page_url, candidate.query]).casefold()
    if any(token in hay for token in ("nypd", "berlin polizei", "tokyo")):
        return False
    return True


def search_pexels_family(
    paths: ProjectPaths,
    *,
    scene: Scene,
    family: str,
    queries: tuple[str, ...],
    used_ids: set[str],
    provider: PexelsStockVideoProvider | None = None,
) -> StockVideoCandidate | None:
    client = provider or PexelsStockVideoProvider()
    ranked: list[StockVideoCandidate] = []
    for query in queries[:MAX_QUERY_VARIANTS]:
        cache_path = _search_cache_path(paths, query)
        if cache_path.is_file():
            raw = json.loads(cache_path.read_text(encoding="utf-8"))
            page_videos = [StockVideoCandidate.model_validate(item) for item in raw]
        else:
            page = client.search(query, per_page=PER_PAGE)
            page_videos = page.videos
            cache_path.write_text(
                json.dumps([item.model_dump(mode="json") for item in page_videos]),
                encoding="utf-8",
            )
        for raw in page_videos:
            scored = score_candidate(raw.model_copy(update={"query": query}), scene, query)
            ranked.append(scored)
        best_now = [
            item
            for item in ranked
            if _usable(item, family) and item.provider_video_id not in used_ids
        ]
        if best_now:
            leader = max(best_now, key=lambda item: _family_score(item, family))
            if _family_score(leader, family) >= 45:
                return leader
    usable = [
        item
        for item in ranked
        if _usable(item, family) and item.provider_video_id not in used_ids
    ]
    if not usable:
        return None
    return max(usable, key=lambda item: _family_score(item, family))


def download_stock_candidate(
    paths: ProjectPaths,
    *,
    project: Project,
    scene: Scene,
    candidate: StockVideoCandidate,
    provider: PexelsStockVideoProvider | None = None,
) -> str:
    from docprod.stock.base import StockVideoProvider

    client: StockVideoProvider = provider or PexelsStockVideoProvider()
    rendition = choose_rendition(candidate.video_files)
    if rendition is None:
        raise ValueError("no rendition")
    dest = paths.stock_source_mp4(scene.id)
    dest.parent.mkdir(parents=True, exist_ok=True)
    download_file(client, rendition.link, dest)
    needed = float(scene.duration)
    start = pick_clip_start(
        source_duration=probe_media(dest).duration,
        needed=needed,
        seed=project.random_seed,
        scene_id=scene.id,
    )
    clip = paths.stock_clip_mp4(scene.id)
    sha = normalize_stock_clip(dest, clip, start=start, duration=needed)
    save_model(
        paths.stock_source_meta(scene.id),
        StockSourceManifest(
            scene_id=scene.id,
            provider=candidate.provider,
            provider_video_id=candidate.provider_video_id,
            source_page_url=candidate.source_page_url,
            creator_name=candidate.creator_name,
            duration=probe_media(dest).duration,
            width=1280,
            height=720,
            download_url=rendition.link,
            downloaded_path=dest.relative_to(paths.root).as_posix(),
            sha256=file_sha256(dest),
            query=candidate.query,
            clip_start=start,
            clip_duration=needed,
            clip_path=clip.relative_to(paths.root).as_posix(),
            clip_sha256=sha,
        ),
    )
    return dest.relative_to(paths.root).as_posix()


def search_scc_archive(
    scene: Scene, commons: WikimediaCommonsProvider
) -> ArchiveCandidate | None:
    ranked: list[ArchiveCandidate] = []
    for query in SCC_QUERIES:
        try:
            page = commons.search_files(query, limit=12)
        except Exception:  # noqa: BLE001
            continue
        for raw in page:
            scored = score_archive_candidate(raw, scene=scene, query=query)
            title = scored.title.casefold()
            if "supreme court of canada" not in title and "cour suprême du canada" not in title:
                scored = scored.model_copy(update={"score": scored.score - 40})
            else:
                scored = scored.model_copy(update={"score": scored.score + 25})
            if scored.decision != "AUTO_REUSABLE":
                continue
            if scored.width < 800:
                continue
            ranked.append(scored)
    if not ranked:
        return None
    return max(ranked, key=lambda item: item.score)


def _extract_still(video: Path, dest: Path, timestamp: float = 1.0) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(
        ["-ss", f"{timestamp:.3f}", "-i", str(video), "-frames:v", "1", "-q:v", "3", str(dest)],
        timeout=30,
    )


def _bind_still_jpeg(source: Path, dest: Path) -> None:
    from docprod.pipeline.replace_explainer_visuals import _write_preview_still

    dest.parent.mkdir(parents=True, exist_ok=True)
    _write_preview_still(source, dest)


def apply_diversity_item(
    paths: ProjectPaths,
    *,
    project: Project,
    plan: ScenePlan,
    asset_plan: AssetPlan,
    item: DiversityItem,
    used_ids: set[str],
    library: dict[str, list[Path]],
    session_uses: Counter[str],
    stats: DiversityLiveStats,
    pexels: bool,
    commons_on: bool,
    provider: PexelsStockVideoProvider | None = None,
    commons: WikimediaCommonsProvider | None = None,
) -> None:
    from docprod.pipeline.replace_explainer_visuals import bind_stock_clip

    scenes = {scene.id: scene for scene in plan.scenes}
    first = scenes[item.scene_ids[0]]
    unit = next(row for row in asset_plan.units if row.asset_unit_id == item.unit_id)
    queries = POLICE_FAMILIES.get(item.family) or MAPLE_VARIETY_QUERIES.get(item.family)
    if item.family in {"court"}:
        queries = COURT_QUERIES
    if item.family == "scc":
        queries = SCC_QUERIES

    if item.family == "scc" and commons_on:
        client = commons or WikimediaCommonsProvider()
        chosen = search_scc_archive(first, client)
        if chosen is not None and chosen.file_url:
            dest = paths.archive_source_path(item.unit_id, ".jpg")
            download_archive_file(client, chosen.file_url, dest)
            _bind_still_jpeg(dest, dest)
            item.reuse_path = dest.relative_to(paths.root).as_posix()
            item.action = "archive"
            item.provider = "wikimedia_commons"
            stats.new_archive_downloads += 1
            second = dest.parent / "seq_1.jpg"
            court_clip = next(iter(library.get("court") or []), None)
            if court_clip is not None:
                _extract_still(court_clip, second, 1.2)
                item.sequence_paths = [dest.as_posix(), second.as_posix()]
                item.action = "photo_sequence"
            save_model(
                paths.archive_source_meta(item.unit_id),
                ArchiveSourceManifest(
                    asset_unit_id=item.unit_id,
                    title=chosen.title,
                    description_url=chosen.description_url,
                    file_url=chosen.file_url,
                    artist=chosen.artist,
                    credit=chosen.credit,
                    license_short_name=chosen.license_short_name,
                    license_url=chosen.license_url,
                    usage_terms=chosen.usage_terms,
                    attribution_text=chosen.attribution or chosen.artist,
                    attribution_required=chosen.attribution_required,
                    restrictions=chosen.restrictions,
                    retrieved_at="2026-09-19T00:00:00+00:00",
                    sha256=file_sha256(dest),
                    local_path=item.reuse_path,
                    width=chosen.width,
                    height=chosen.height,
                ),
            )
        else:
            item.action = "new_stock"
            item.family = "court"
            queries = COURT_QUERIES

    if item.action in {"new_stock", "existing_stock"} and not item.reuse_path:
        existing = list(library.get(item.family) or [])
        if item.family == "court":
            existing.extend(library.get("court") or [])
        picked_path: Path | None = None
        for candidate_path in existing:
            digest = file_fingerprint(candidate_path)
            if digest == item.old_source_id:
                continue
            if session_uses[digest] >= 2:
                continue
            picked_path = candidate_path
            break
        if picked_path is None and pexels and queries:
            patched = first.model_copy(update={"asset_strategy": AssetStrategy.stock_video})
            best = search_pexels_family(
                paths,
                scene=patched,
                family=item.family,
                queries=queries,
                used_ids=used_ids,
                provider=provider,
            )
            if best is not None:
                rel = download_stock_candidate(
                    paths, project=project, scene=first, candidate=best, provider=provider
                )
                item.reuse_path = rel
                item.action = "new_stock"
                item.provider = "pexels"
                used_ids.add(best.provider_video_id)
                stats.new_stock_downloads += 1
                src = paths.root / rel
                library.setdefault(item.family, []).append(src)
                session_uses[file_fingerprint(src)] += 1
                picked_path = None
        if picked_path is not None:
            rel = bind_stock_clip(
                paths, first, picked_path, seed=project.random_seed, duration=first.duration
            )
            item.reuse_path = rel
            item.provider = "existing_stock"
            session_uses[file_fingerprint(picked_path)] += 1
        elif item.reuse_path:
            pass
        elif existing:
            rel = bind_stock_clip(
                paths, first, existing[0], seed=project.random_seed, duration=first.duration
            )
            item.reuse_path = rel
            item.provider = "existing_stock"

    if item.reuse_path:
        source = Path(item.reuse_path)
        if not source.is_file():
            source = paths.root / item.reuse_path
        for extra_id in item.scene_ids[1:]:
            extra_scene = scenes[extra_id]
            if source.suffix.lower() == ".mp4" and source.is_file():
                bind_stock_clip(
                    paths,
                    extra_scene,
                    source,
                    seed=project.random_seed,
                    duration=extra_scene.duration,
                )
        strategy = (
            AssetStrategy.archive_image
            if item.action in {"archive", "photo_sequence"}
            else AssetStrategy.stock_video
        )
        extra = dict(unit.extra)
        extra["diversity_v3"] = item.reason
        extra["source_fingerprint"] = (
            file_fingerprint(source) if source.is_file() else item.old_source_id
        )
        if item.sequence_paths:
            extra["photo_sequence"] = PhotoSequenceAsset(
                stills=item.sequence_paths, concept_keys=[item.family]
            ).model_dump()
        unit.source_strategy = strategy
        unit.status = "READY_ARCHIVE" if strategy is AssetStrategy.archive_image else "READY_STOCK"
        unit.source_path = item.reuse_path
        unit.extra = extra
        unit.visual_concept = item.family
        for index, scene_id in enumerate(item.scene_ids):
            scene = scenes[scene_id]
            converted = _apply_strategy(scene, strategy, "visual_v3_diversity")
            meta = dict(converted.metadata)
            if item.sequence_paths:
                meta["photo_sequence"] = item.sequence_paths
                meta["photo_sequence_index"] = min(index, len(item.sequence_paths) - 1)
                meta["photo_sequence_split"] = "1"
                converted = converted.model_copy(
                    update={
                        "effect": STILL_EFFECTS[index % len(STILL_EFFECTS)],
                        "metadata": meta,
                    }
                )
            scenes[scene_id] = converted
        for index, scene in enumerate(plan.scenes):
            plan.scenes[index] = scenes[scene.id]


def execute_diversity(
    paths: ProjectPaths,
    *,
    project: Project,
    plan: ScenePlan,
    asset_plan: AssetPlan,
    report: DiversityReport,
    enable_pexels: bool,
    enable_commons: bool,
    provider: PexelsStockVideoProvider | None = None,
    commons: WikimediaCommonsProvider | None = None,
) -> tuple[ScenePlan, AssetPlan, DiversityReport, DiversityLiveStats]:
    stats = DiversityLiveStats(paid_api_calls=0)
    library = index_existing_stock(paths)
    used_ids: set[str] = set()
    session_uses: Counter[str] = Counter()
    for unit in asset_plan.units:
        scene = next(row for row in plan.scenes if row.id == unit.scene_ids[0])
        meta = paths.stock_source_meta(scene.id)
        if meta.is_file():
            try:
                payload = json.loads(meta.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                payload = {}
            vid = str(payload.get("provider_video_id") or "")
            if vid and vid != "reused":
                used_ids.add(vid)
    for item in report.items:
        apply_diversity_item(
            paths,
            project=project,
            plan=plan,
            asset_plan=asset_plan,
            item=item,
            used_ids=used_ids,
            library=library,
            session_uses=session_uses,
            stats=stats,
            pexels=enable_pexels,
            commons_on=enable_commons,
            provider=provider,
            commons=commons,
        )
    report.paid_api_calls = stats.paid_api_calls
    assert report.paid_api_calls == 0
    return plan, asset_plan, report, stats


def write_diversity_markdown(paths: ProjectPaths, report: DiversityReport) -> Path:
    dest = paths.visual_diversity_v3_md()
    lines = [
        "# Visual diversity v3",
        "",
        f"- unique sources (before): {report.unique_sources}",
        f"- max reuse (before): {report.max_reuse}",
        f"- police duplicate max (before): {report.police_duplicate_max}",
        f"- court mismatches (before): {report.court_mismatch}",
        f"- paid API calls: {report.paid_api_calls}",
        "",
        "## Changes",
        "",
    ]
    for item in report.items:
        lines.append(
            f"- `{item.unit_id}` [{item.priority}] {item.reason} → {item.family} "
            f"({item.action}/{item.provider or 'planned'}): {item.narration_snippet}"
        )
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return dest


def write_diversity_contact_sheet(paths: ProjectPaths, report: DiversityReport) -> Path | None:
    from PIL import Image, ImageDraw

    from docprod.graphics.fonts import discover_sans_font, load_font

    if not report.items:
        return None
    tile_w, tile_h, label_h = 320, 180, 64
    cols = 2
    rows = len(report.items)
    sheet = Image.new("RGB", (cols * tile_w, rows * (tile_h + label_h)), (10, 10, 12))
    draw = ImageDraw.Draw(sheet)
    font = load_font(discover_sans_font(), 12)

    def thumb(path: Path | None) -> Image.Image:
        canvas = Image.new("RGB", (tile_w, tile_h), (30, 30, 36))
        if path is None or not path.is_file():
            return canvas
        try:
            image = Image.open(path).convert("RGB")
        except OSError:
            return canvas
        image.thumbnail((tile_w, tile_h))
        canvas.paste(image, ((tile_w - image.width) // 2, (tile_h - image.height) // 2))
        return canvas

    for index, item in enumerate(report.items):
        y = index * (tile_h + label_h)
        old = Path(item.old_source_id)
        # old thumbnail from previous stock clip of first scene
        first_id = item.scene_ids[0]
        old_clip = paths.stock_clip_mp4(first_id)
        old_still = paths.archive_source_path(item.unit_id, ".jpg")
        new_path = Path(item.reuse_path) if item.reuse_path else None
        if new_path and not new_path.is_file():
            new_path = paths.root / item.reuse_path if item.reuse_path else None
        if item.sequence_paths:
            seq = Path(item.sequence_paths[0])
            new_path = seq if seq.is_file() else new_path
        sheet.paste(thumb(old_clip if old_clip.is_file() else old_still), (0, y))
        sheet.paste(thumb(new_path), (tile_w, y))
        label = (
            f"{item.unit_id} {','.join(item.scene_ids)} {item.family} "
            f"{item.provider or item.action}"
        )[:80]
        draw.text((8, y + tile_h + 4), label, font=font, fill=(230, 230, 230))
        draw.text(
            (8, y + tile_h + 22), item.narration_snippet[:70], font=font, fill=(180, 180, 180)
        )
        _ = old
    dest = paths.visual_diversity_v3_contact_sheet()
    dest.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(dest, quality=88)
    return dest


def render_visual_v3(
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
        output_mp4=paths.preview_visual_v3_mp4(),
        manifest_path=paths.preview_visual_v3_manifest(),
        captions_srt=paths.captions_narrated_srt(),
        captions_ass=paths.captions_narrated_ass(),
        narration_wav=paths.narration_master_wav(),
        allow_placeholders=False,
        alignment=alignment,
        write_caption_files=False,
    )
    return result.cache_hits, result.rendered_segments, perf_counter() - started


def backup_plans(paths: ProjectPaths) -> None:
    review = paths.review_dir
    review.mkdir(parents=True, exist_ok=True)
    for src, name in (
        (paths.scene_plan_json, "05_scenes_pre_visual_v3.json"),
        (paths.asset_plan_json(), "06_asset_plan_pre_visual_v3.json"),
    ):
        if src.is_file():
            shutil.copy2(src, review / name)
