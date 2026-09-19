from __future__ import annotations

from docprod.archive.models import ArchiveCandidate
from docprod.models.scene import Scene

_GENERIC_PENALTY = ("logo", "icon", "svg diagram", "coat of arms")
_AGENCY_MISMATCH = ("nypd", "berlin polizei", "tokyo station")


def score_archive_candidate(
    candidate: ArchiveCandidate,
    *,
    scene: Scene,
    query: str,
) -> ArchiveCandidate:
    reasons: list[str] = []
    score = 0.0
    hay = " ".join(
        [
            candidate.title,
            candidate.description,
            query,
            candidate.artist,
        ]
    ).casefold()
    for token in query.casefold().split():
        if len(token) > 3 and token in hay:
            score += 6
            reasons.append(f"query:{token}")
    if candidate.width >= 1280 and candidate.height >= 720:
        score += 15
        reasons.append("hd")
    elif candidate.width and candidate.width < 800:
        score -= 20
        reasons.append("low_res")
    if candidate.width >= candidate.height:
        score += 10
        reasons.append("landscape")
    else:
        score -= 12
        reasons.append("portrait")
    if candidate.media_type == "BITMAP" or candidate.mime.startswith("image/"):
        score += 8
        reasons.append("still_image")
    elif candidate.media_type in {"VIDEO", "AUDIO"} or "video" in candidate.mime:
        score += 4
        reasons.append("av_file")
    else:
        score -= 50
        reasons.append("non_image_file")
    if any(year in hay for year in ("1908", "1920", "1923", "19th")):
        score -= 20
        reasons.append("era_mismatch")
    if candidate.decision == "AUTO_REUSABLE":
        score += 20
        reasons.append("auto_reusable")
    elif candidate.decision == "REJECT":
        score -= 80
        reasons.append("rejected_license")
    else:
        score -= 5
        reasons.append("license_review")
    intent = f"{scene.visual_intent} {scene.metadata.get('visual_subject') or ''}".casefold()
    if "barrel" in intent and "barrel" in hay:
        score += 8
        reasons.append("barrel_match")
    if "quebec" in intent and "quebec" in hay:
        score += 8
        reasons.append("place_match")
    if "acer" in hay or "botanical" in hay:
        if any(
            token in intent for token in ("warehouse", "depo", "barrel", "fıçı", "court", "mahkeme")
        ):
            score -= 28
            reasons.append("botanical_mismatch")
    if any(token in hay for token in _GENERIC_PENALTY):
        score -= 15
        reasons.append("generic_or_logo")
    if any(token in hay for token in _AGENCY_MISMATCH):
        score -= 25
        reasons.append("agency_mismatch")
    return candidate.model_copy(update={"score": round(score, 3), "score_reasons": reasons})
