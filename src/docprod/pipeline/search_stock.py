from __future__ import annotations

from datetime import UTC, datetime

from docprod.exceptions import StockProviderError
from docprod.logging_utils import get_logger
from docprod.models.enums import AssetStrategy
from docprod.models.project import Project
from docprod.models.scene import Scene, ScenePlan
from docprod.render.ffmpeg import probe_media
from docprod.stock import PEXELS_VIDEO_SEARCH_URL, STOCK_LICENSE_NOTE
from docprod.stock.base import StockVideoProvider
from docprod.stock.contact import build_candidate_contact_sheet
from docprod.stock.downloader import (
    adjust_start_away_from_black,
    download_file,
    normalize_stock_clip,
    pick_clip_start,
    rendition_payload,
)
from docprod.stock.manifest import rebuild_credits
from docprod.stock.models import (
    SceneStockSearchResult,
    StockSearchManifest,
    StockSourceManifest,
    StockVideoCandidate,
)
from docprod.stock.pexels import PexelsStockVideoProvider
from docprod.stock.query import generate_stock_queries
from docprod.stock.scoring import choose_rendition, score_candidate
from docprod.storage.json_store import load_model, save_model
from docprod.storage.paths import ProjectPaths

_LOG = get_logger("stock.search")

STOCK_STRATEGIES = frozenset({AssetStrategy.stock_video, AssetStrategy.archive_video})
MAX_UNIQUE = 40
PER_PAGE = 20


def _stock_scenes(plan: ScenePlan, scene_id: str | None) -> list[Scene]:
    scenes = [scene for scene in plan.scenes if scene.asset_strategy in STOCK_STRATEGIES]
    if scene_id is not None:
        scenes = [scene for scene in scenes if scene.id == scene_id]
        if not scenes:
            raise StockProviderError(f"No stock/archive scene matching {scene_id}")
    return scenes


def _merge_candidate(
    existing: dict[str, StockVideoCandidate],
    candidate: StockVideoCandidate,
) -> None:
    prior = existing.get(candidate.provider_video_id)
    if prior is None or candidate.score > prior.score:
        existing[candidate.provider_video_id] = candidate


def search_stock(
    paths: ProjectPaths,
    *,
    project: Project,
    plan: ScenePlan,
    provider: StockVideoProvider | None = None,
    scene_id: str | None = None,
    locale: str = "en-US",
) -> StockSearchManifest:
    client = provider or PexelsStockVideoProvider()
    results: list[SceneStockSearchResult] = []
    last_limit = last_remaining = last_reset = None
    paths.stock_candidates_dir.mkdir(parents=True, exist_ok=True)
    for scene in _stock_scenes(plan, scene_id):
        queries = generate_stock_queries(scene)
        unique: dict[str, StockVideoCandidate] = {}
        for query in queries:
            page = client.search(query, per_page=PER_PAGE, locale=locale)
            last_limit = page.ratelimit_limit
            last_remaining = page.ratelimit_remaining
            last_reset = page.ratelimit_reset
            for raw in page.videos:
                scored = score_candidate(raw, scene, query)
                _merge_candidate(unique, scored)
                if len(unique) >= MAX_UNIQUE:
                    break
            if len(unique) >= MAX_UNIQUE:
                break
        ranked = sorted(unique.values(), key=lambda item: item.score, reverse=True)
        sheet_path = paths.stock_scene_candidates_sheet(scene.id)
        sheet = build_candidate_contact_sheet(ranked, sheet_path, provider=client)
        results.append(
            SceneStockSearchResult(
                scene_id=scene.id,
                narration=scene.narration,
                queries=queries,
                candidates=ranked,
                contact_sheet=str(sheet) if sheet else None,
            )
        )
        _LOG.info(
            "Stock search %s queries=%s unique=%s",
            scene.id,
            queries,
            len(ranked),
        )
    retrieved = datetime.now(UTC).isoformat()
    if scene_id is None or not paths.stock_candidates_json().is_file():
        manifest = StockSearchManifest(
            project_id=project.id,
            search_url=PEXELS_VIDEO_SEARCH_URL,
            scenes=results,
            ratelimit_limit=last_limit,
            ratelimit_remaining=last_remaining,
            ratelimit_reset=last_reset,
            retrieved_at=retrieved,
        )
    else:
        manifest = load_model(paths.stock_candidates_json(), StockSearchManifest)
        by_id = {item.scene_id: item for item in manifest.scenes}
        for item in results:
            by_id[item.scene_id] = item
        manifest = manifest.model_copy(
            update={
                "scenes": list(by_id.values()),
                "ratelimit_limit": last_limit,
                "ratelimit_remaining": last_remaining,
                "ratelimit_reset": last_reset,
                "retrieved_at": retrieved,
            }
        )
    save_model(paths.stock_candidates_json(), manifest)
    return manifest


def _candidate_for_scene(
    manifest: StockSearchManifest, scene_id: str, video_id: str
) -> StockVideoCandidate:
    for scene in manifest.scenes:
        if scene.scene_id != scene_id:
            continue
        for candidate in scene.candidates:
            if candidate.provider_video_id == video_id:
                return candidate
    raise StockProviderError(
        f"Pexels video {video_id} is not in search candidates for {scene_id}"
    )


def select_stock(
    paths: ProjectPaths,
    *,
    project: Project,
    plan: ScenePlan,
    scene_id: str,
    video_id: str,
    provider: StockVideoProvider | None = None,
) -> StockSourceManifest:
    if not paths.stock_candidates_json().is_file():
        raise StockProviderError("Run search-stock before select-stock")
    search = load_model(paths.stock_candidates_json(), StockSearchManifest)
    candidate = _candidate_for_scene(search, scene_id, video_id)
    scene = next((item for item in plan.scenes if item.id == scene_id), None)
    if scene is None:
        raise StockProviderError(f"Unknown scene {scene_id}")
    if candidate.rejected and candidate.reject_reason == "too_short_for_scene":
        raise StockProviderError(f"Candidate {video_id} is too short for {scene_id}")
    rendition = choose_rendition(candidate.video_files)
    if rendition is None:
        raise StockProviderError(f"No suitable MP4 rendition for {video_id}")
    client = provider or PexelsStockVideoProvider()
    dest_dir = paths.stock_scene_dir(scene_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    source_path = paths.stock_source_mp4(scene_id)
    sha = download_file(client, rendition.link, source_path)
    probe = probe_media(source_path)
    source_duration = probe.duration or candidate.duration
    needed = float(scene.duration)
    if source_duration < needed + 0.25:
        source_path.unlink(missing_ok=True)
        raise StockProviderError(f"Downloaded source is too short for {scene_id}")
    start = pick_clip_start(
        source_duration=source_duration,
        needed=needed,
        seed=project.random_seed,
        scene_id=scene_id,
    )
    start = adjust_start_away_from_black(source_path, start, needed, source_duration)
    clip_path = paths.stock_clip_mp4(scene_id)
    clip_sha = normalize_stock_clip(source_path, clip_path, start=start, duration=needed)
    rel_source = source_path.relative_to(paths.root).as_posix()
    rel_clip = clip_path.relative_to(paths.root).as_posix()
    meta = StockSourceManifest(
        scene_id=scene_id,
        provider=candidate.provider,
        provider_video_id=candidate.provider_video_id,
        source_page_url=candidate.source_page_url,
        creator_name=candidate.creator_name,
        creator_url=candidate.creator_url,
        duration=source_duration,
        width=probe.width or candidate.width,
        height=probe.height or candidate.height,
        fps=probe.fps or candidate.fps,
        download_url=rendition.link,
        downloaded_path=rel_source,
        sha256=sha,
        query=candidate.query,
        license_note=STOCK_LICENSE_NOTE,
        selected_rendition=rendition_payload(rendition),
        clip_start=start,
        clip_duration=needed,
        clip_path=rel_clip,
        clip_sha256=clip_sha,
        effect_override_reason="native_video_motion",
        retrieved_at=datetime.now(UTC).isoformat(),
    )
    save_model(paths.stock_source_meta(scene_id), meta)
    rebuild_credits(paths, project.id)
    return meta


def select_stock_auto(
    paths: ProjectPaths,
    *,
    project: Project,
    plan: ScenePlan,
    scene_id: str,
    provider: StockVideoProvider | None = None,
) -> StockSourceManifest:
    if not paths.stock_candidates_json().is_file():
        raise StockProviderError("Run search-stock before select-stock-auto")
    search = load_model(paths.stock_candidates_json(), StockSearchManifest)
    scene_result = next((item for item in search.scenes if item.scene_id == scene_id), None)
    if scene_result is None:
        raise StockProviderError(f"No search candidates for {scene_id}")
    usable = [item for item in scene_result.candidates if not item.rejected]
    if not usable:
        raise StockProviderError(f"No non-rejected candidates for {scene_id}")
    best = max(usable, key=lambda item: item.score)
    return select_stock(
        paths,
        project=project,
        plan=plan,
        scene_id=scene_id,
        video_id=best.provider_video_id,
        provider=provider,
    )
