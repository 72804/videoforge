from __future__ import annotations

import re

from docprod.audio.boundaries import NarrationBoundaryValidator
from docprod.audio.models import (
    DEFAULT_VOICE_INSTRUCTIONS,
    TTS_CONTINUATION_INSTRUCTIONS,
    TTS_ONCE_INSTRUCTIONS,
    CanonicalNarrationScript,
    NarrationChunkManifest,
    NarrationChunkSpec,
)
from docprod.audio.script import tokenize_display
from docprod.audio.tts_preflight import TTS_MAX_INPUT_CHARS, estimate_tts_tokens
from docprod.exceptions import TtsInputLimitError
from docprod.models.scene import ScenePlan
from docprod.storage.hashing import content_hash

TTS_API_MAX_INPUT_CHARS = TTS_MAX_INPUT_CHARS
TTS_SAFE_CHUNK_CHARS = 3600

_ABBREV = {
    "dr",
    "mr",
    "mrs",
    "ms",
    "prof",
    "vs",
    "no",
    "sn",
    "st",
    "vd",
    "vb",
    "örn",
    "orn",
    "etc",
}
_WORD_RE = re.compile(r"[\wğüşöçıİĞÜŞÖÇ']+", re.UNICODE)


def _word_spans(text: str) -> list[tuple[int, int]]:
    return [(match.start(), match.end()) for match in _WORD_RE.finditer(text)]


def _chapters(plan: ScenePlan | None, script: CanonicalNarrationScript) -> list[str]:
    if plan is None:
        return [""] * len(script.spans)
    by_id = {scene.id: str(scene.metadata.get("chapter") or "") for scene in plan.scenes}
    return [by_id.get(span.scene_id, "") for span in script.spans]


def _is_abbrev(text: str, period_index: int) -> bool:
    start = period_index
    while start > 0 and text[start - 1].isalpha():
        start -= 1
    token = text[start:period_index].casefold()
    return token in _ABBREV


def _inside_number(text: str, period_index: int) -> bool:
    prev_d = period_index > 0 and text[period_index - 1].isdigit()
    next_d = period_index + 1 < len(text) and text[period_index + 1].isdigit()
    return prev_d and next_d


def _inside_word(text: str, index: int) -> bool:
    if index <= 0 or index >= len(text):
        return False
    left = text[index - 1]
    right = text[index]
    return bool(_WORD_RE.match(left) and _WORD_RE.match(right))


def _quote_unbalanced(text: str, start: int, end: int) -> bool:
    slice_ = text[start:end]
    return slice_.count('"') % 2 == 1 or slice_.count("“") != slice_.count("”")


def _chunk_instructions(index: int) -> str:
    if index > 1:
        return (
            f"{DEFAULT_VOICE_INSTRUCTIONS} {TTS_CONTINUATION_INSTRUCTIONS} "
            f"{TTS_ONCE_INSTRUCTIONS}"
        )
    return f"{DEFAULT_VOICE_INSTRUCTIONS} {TTS_ONCE_INSTRUCTIONS}"


def _boundary_candidates(
    text: str,
    start: int,
    limit: int,
    *,
    script: CanonicalNarrationScript,
    chapters: list[str],
) -> list[tuple[int, str, int]]:
    """Return (split_index, kind, rank) with lower rank preferred."""
    found: list[tuple[int, str, int]] = []
    for span, chapter, nxt_chapter in zip(
        script.spans, chapters, chapters[1:] + [chapters[-1] if chapters else ""], strict=False
    ):
        if span.char_end <= start or span.char_end > limit:
            continue
        if chapter and nxt_chapter and chapter != nxt_chapter:
            found.append((span.char_end, "chapter", 0))
    for span in script.spans:
        if start < span.char_end <= limit and span.char_end < len(text):
            found.append((span.char_end, "scene", 2))
    for match in re.finditer(r"\n\n+", text[start:limit]):
        found.append((start + match.end(), "paragraph", 1))
    index = start
    while index < limit:
        char = text[index]
        if char in ".!?":
            if not _is_abbrev(text, index) and not _inside_number(text, index):
                split = index + 1
                while split < len(text) and text[split] in "\"'”’":
                    split += 1
                if split <= limit:
                    found.append((split, "sentence", 2))
        elif char in ";:—":
            found.append((index + 1, "clause", 3))
        elif char == "," and index > start:
            found.append((index + 1, "punctuation", 4))
        index += 1
    return found


def _pick_split(
    text: str,
    start: int,
    preferred: int,
    hard: int,
    *,
    script: CanonicalNarrationScript,
    chapters: list[str],
) -> tuple[int, str]:
    remaining = len(text) - start
    if remaining <= preferred:
        return len(text), "end"
    preferred_end = min(len(text), start + preferred)
    hard_end = min(len(text), start + hard)

    validator = NarrationBoundaryValidator()

    def choose(
        limit: int, *, allow_clause: bool, allow_last_resort: bool
    ) -> tuple[int, str] | None:
        cands = [
            item
            for item in _boundary_candidates(
                text, start, limit, script=script, chapters=chapters
            )
            if item[0] > start
            and item[0] <= limit
            and not _inside_word(text, item[0])
            and not _quote_unbalanced(text, start, item[0])
            and validator.is_safe(text, item[0])
        ]
        if not allow_clause:
            cands = [item for item in cands if item[1] not in {"clause", "punctuation"}]
        elif not allow_last_resort:
            cands = [item for item in cands if item[1] != "punctuation"]
        if not cands:
            return None
        best = min(cands, key=lambda item: (item[2], -item[0]))
        return best[0], best[1]

    picked = choose(preferred_end, allow_clause=False, allow_last_resort=False)
    if picked is None:
        picked = choose(hard_end, allow_clause=False, allow_last_resort=False)
    if picked is None:
        picked = choose(hard_end, allow_clause=True, allow_last_resort=False)
    if picked is None:
        picked = choose(hard_end, allow_clause=True, allow_last_resort=True)
    if picked is not None:
        return picked
    cursor = hard_end
    while cursor > start and not text[cursor - 1].isspace():
        cursor -= 1
    if cursor > start:
        reason = validator.reason(text, cursor)
        if reason in {None, "mid_sentence"}:
            return cursor, "whitespace"
    raise TtsInputLimitError(
        f"Cannot split narration into Speech API chunks of {hard} characters "
        "without cutting an unsafe linguistic span."
    )


class NarrationChunkPlanner:
    def __init__(
        self,
        *,
        safe_chars: int = TTS_SAFE_CHUNK_CHARS,
        max_chars: int = TTS_API_MAX_INPUT_CHARS,
    ) -> None:
        self.safe_chars = safe_chars
        self.max_chars = max_chars

    def plan(
        self,
        script: CanonicalNarrationScript,
        plan: ScenePlan | None = None,
    ) -> NarrationChunkManifest:
        text = script.text
        chapters = _chapters(plan, script)
        words = _word_spans(text)
        chunks: list[NarrationChunkSpec] = []
        cursor = 0
        join_kind = "start"
        while cursor < len(text):
            split, kind = _pick_split(
                text,
                cursor,
                self.safe_chars,
                self.max_chars,
                script=script,
                chapters=chapters,
            )
            piece = text[cursor:split]
            if not piece:
                raise TtsInputLimitError("Empty narration chunk produced.")
            if len(piece) > self.max_chars:
                raise TtsInputLimitError(
                    f"Chunk length {len(piece)} exceeds {self.max_chars} characters."
                )
            word_start = next(
                (i for i, (_a, end) in enumerate(words) if end > cursor), len(words)
            )
            word_end = next(
                (i for i, (begin, _b) in enumerate(words) if begin >= split), len(words)
            )
            overlapping = [
                (span, chapter)
                for span, chapter in zip(script.spans, chapters, strict=False)
                if span.char_end > cursor and span.char_start < split
            ]
            chapter_start = overlapping[0][1] if overlapping else ""
            chapter_end = overlapping[-1][1] if overlapping else ""
            index = len(chunks) + 1
            instructions = _chunk_instructions(index)
            reason = "start" if join_kind == "start" else join_kind
            chunks.append(
                NarrationChunkSpec(
                    chunk_id=f"chunk_{index:03d}",
                    chunk_index=index,
                    text=piece,
                    char_start=cursor,
                    char_end=split,
                    word_start=word_start,
                    word_end=word_end,
                    chapter_start=chapter_start,
                    chapter_end=chapter_end,
                    character_count=len(piece),
                    estimated_token_count=estimate_tts_tokens(piece),
                    script_hash=content_hash(piece),
                    boundary_type=join_kind,
                    instructions=instructions,
                    boundary_reason=reason,
                )
            )
            join_kind = kind
            cursor = split
        reconstructed = "".join(item.text for item in chunks)
        if reconstructed != text:
            raise TtsInputLimitError("Chunk concatenation does not match canonical narration.")
        return NarrationChunkManifest(
            project_id=script.project_id,
            canonical_character_count=len(text),
            canonical_word_count=len(tokenize_display(text)),
            chunk_count=len(chunks),
            canonical_script_hash=content_hash(text),
            chunks=chunks,
        )


def validate_chunk_manifest(
    manifest: NarrationChunkManifest, script: CanonicalNarrationScript
) -> None:
    if "".join(item.text for item in manifest.chunks) != script.text:
        raise TtsInputLimitError("Chunk reconstruction failed.")
    seen_words: set[int] = set()
    cursor = 0
    for item in manifest.chunks:
        if item.character_count > TTS_API_MAX_INPUT_CHARS:
            raise TtsInputLimitError(f"{item.chunk_id} exceeds API character max.")
        if item.char_start != cursor or item.char_end < item.char_start:
            raise TtsInputLimitError("Chunk character spans are not monotonic.")
        for word in range(item.word_start, item.word_end):
            if word in seen_words:
                raise TtsInputLimitError("Chunk word spans overlap.")
            seen_words.add(word)
        cursor = item.char_end
    if cursor != len(script.text):
        raise TtsInputLimitError("Chunk spans do not cover the canonical script.")
