from __future__ import annotations

import re
import unicodedata

from docprod.audio.models import CanonicalNarrationScript, SceneNarrationSpan
from docprod.models.scene import ScenePlan

_WORD_RE = re.compile(r"[\wğüşöçıİĞÜŞÖÇ']+", re.UNICODE)


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def fold_token(text: str) -> str:
    swapped = text.replace("İ", "i").replace("I", "i").replace("ı", "i")
    stripped = "".join(
        char for char in unicodedata.normalize("NFKD", swapped) if not unicodedata.combining(char)
    )
    cleaned = re.sub(r"[^\w]+", "", stripped, flags=re.UNICODE)
    return cleaned.casefold()


def tokenize_display(text: str) -> list[str]:
    return _WORD_RE.findall(text)


def build_canonical_script(plan: ScenePlan) -> CanonicalNarrationScript:
    spans: list[SceneNarrationSpan] = []
    pieces: list[str] = []
    cursor = 0
    for scene in plan.scenes:
        narration = normalize_whitespace(scene.narration)
        if pieces:
            cursor += 1  # joining space
        start = cursor
        pieces.append(narration)
        cursor += len(narration)
        spans.append(
            SceneNarrationSpan(
                scene_id=scene.id,
                narration=narration,
                char_start=start,
                char_end=cursor,
                planned_duration=float(scene.duration),
            )
        )
    text = " ".join(pieces)
    return CanonicalNarrationScript(project_id=plan.project_id, text=text, spans=spans)
