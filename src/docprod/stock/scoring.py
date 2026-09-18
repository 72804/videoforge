from __future__ import annotations

from docprod.models.scene import Scene
from docprod.stock.models import StockVideoCandidate, StockVideoFile


def _aspect(width: int, height: int) -> float:
    if height <= 0:
        return 0.0
    return width / height


def choose_rendition(files: list[StockVideoFile]) -> StockVideoFile | None:
    """Prefer landscape Full HD MP4; avoid 4K when 1080p exists."""
    usable = [
        item
        for item in files
        if item.width >= item.height
        and item.width >= 1280
        and item.height >= 720
        and "mp4" in (item.file_type or item.link).lower()
    ]
    if not usable:
        usable = [item for item in files if item.width >= item.height and item.width >= 1280]
    if not usable:
        return None

    def rank(item: StockVideoFile) -> tuple[int, int, int, int]:
        is_1080 = int(item.width == 1920 and item.height == 1080)
        is_hd = int(item.width >= 1280)
        not_4k = int(item.width <= 1920)
        closeness = -abs(item.width - 1920) - abs(item.height - 1080)
        return (is_1080, is_hd, not_4k, closeness)

    return max(usable, key=rank)


def score_candidate(
    candidate: StockVideoCandidate,
    scene: Scene,
    query: str,
) -> StockVideoCandidate:
    reasons: list[str] = []
    score = 0.0
    needed = float(scene.duration)
    landscape = candidate.width >= candidate.height
    if landscape:
        score += 25
        reasons.append("landscape")
    else:
        score -= 40
        reasons.append("portrait_penalty")
    if candidate.width >= 1280 and candidate.height >= 720:
        score += 20
        reasons.append("hd_or_better")
    else:
        score -= 25
        reasons.append("low_resolution")
    if candidate.duration >= needed + 0.5:
        score += 20
        reasons.append("duration_ok")
    else:
        score -= 50
        reasons.append("too_short")
    if 5.0 <= candidate.duration <= 40.0:
        score += 8
        reasons.append("useful_length")
    aspect = _aspect(candidate.width, candidate.height)
    if 1.5 <= aspect <= 1.9:
        score += 10
        reasons.append("widescreen")
    elif aspect and (aspect < 1.2 or aspect > 2.4):
        score -= 15
        reasons.append("extreme_aspect")
    if candidate.width == 1920 and candidate.height == 1080:
        score += 8
        reasons.append("full_hd")
    haystack = " ".join(
        [
            candidate.source_page_url,
            candidate.preview_image_url or "",
            str(candidate.extra.get("title") or ""),
        ]
    ).lower()
    overlap = 0
    for token in query.lower().split():
        if len(token) > 2 and token in haystack.replace("-", " "):
            overlap += 1
    if overlap:
        score += 4 * overlap
        reasons.append(f"query_overlap:{overlap}")
    if "animat" in haystack or "cartoon" in haystack:
        score -= 20
        reasons.append("animation_penalty")
    rejected = candidate.duration < needed + 0.25 or not landscape or candidate.width < 1280
    reason = None
    if candidate.duration < needed + 0.25:
        reason = "too_short_for_scene"
    elif not landscape:
        reason = "not_landscape"
    elif candidate.width < 1280:
        reason = "below_720p"
    return candidate.model_copy(
        update={
            "score": round(score, 3),
            "score_reasons": reasons,
            "rejected": rejected,
            "reject_reason": reason,
        }
    )
