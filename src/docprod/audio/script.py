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
    folded = cleaned.casefold()
    aliases = {
        "kebek": "quebec",
        "kebekteki": "quebec",
        "valliers": "vallieres",
        "akcagac": "akcaagac",
        "akcaat": "akcaagac",
        "avi": "avik",
        "avic": "avik",
        "centlik": "sentlik",
        "st": "saint",
    }
    folded = aliases.get(folded, folded)
    dated = re.match(r"^(\d+)(de|da|te|ta|deki|daki)$", folded)
    if dated:
        return dated.group(1)
    return folded


def tokenize_display(text: str) -> list[str]:
    return _WORD_RE.findall(text)


def word_spans(text: str) -> list[tuple[int, int]]:
    return [(match.start(), match.end()) for match in _WORD_RE.finditer(text)]


def slice_punctuated_words(text: str, start_word: int, end_word: int) -> str:
    """Slice original narration so commas/periods/semicolons/apostrophes survive.

    Word indices match tokenize_display. Trailing punctuation after the last
    included word is kept until the next word (or end of text).
    """
    spans = word_spans(text)
    if start_word < 0 or end_word > len(spans) or start_word >= end_word:
        raise ValueError("Invalid narration word slice")
    start = spans[start_word][0]
    if end_word < len(spans):
        stop = spans[end_word][0]
    else:
        stop = len(text)
    return normalize_whitespace(text[start:stop])


def tts_input_text(script: CanonicalNarrationScript) -> str:
    """Text sent to TTS. Punctuation is preserved; do not strip here."""
    return script.text


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
