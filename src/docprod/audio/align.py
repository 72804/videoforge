from __future__ import annotations

import re

from docprod.audio.models import (
    ALIGNMENT_MATCH_THRESHOLD,
    AlignedToken,
    AlignmentReport,
    ChunkAudioWindow,
    WhisperWord,
)
from docprod.audio.script import fold_token, tokenize_display
from docprod.exceptions import AlignmentQualityError
from docprod.models.scene import ScenePlan


def _script_tokens(plan: ScenePlan) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    for scene in plan.scenes:
        for word in tokenize_display(scene.narration):
            tokens.append((word, scene.id))
    return tokens


def _levenshtein(left: str, right: str) -> int:
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)
    previous = list(range(len(right) + 1))
    for i, char_l in enumerate(left, start=1):
        current = [i]
        for j, char_r in enumerate(right, start=1):
            insert = current[j - 1] + 1
            delete = previous[j] + 1
            replace = previous[j - 1] + (0 if char_l == char_r else 1)
            current.append(min(insert, delete, replace))
        previous = current
    return previous[-1]


def _close_tokens(left: str, right: str) -> bool:
    if left == right:
        return True
    if not left or not right:
        return False
    shorter, longer = (left, right) if len(left) <= len(right) else (right, left)
    if shorter in {"st"} and longer == "saint":
        return True
    n = min(len(left), len(right))
    if n < 5:
        return False
    limit = 1 if n < 8 else 2
    if abs(len(left) - len(right)) > limit:
        return False
    return _levenshtein(left, right) <= limit


_NUMBER_SCALES = {"bin": 1000, "yuz": 100, "milyon": 1_000_000}


def _parse_tr_int(tokens: list[str]) -> int | None:
    total = 0
    current = 0
    used = False
    for token in tokens:
        if token.isdigit():
            current += int(token)
            used = True
            continue
        scale = _NUMBER_SCALES.get(token)
        if scale is None:
            return None
        current = max(current, 1) * scale
        total += current
        current = 0
        used = True
    if not used:
        return None
    return total + current


def _group_equivalent(script: list[str], whisper: list[str]) -> bool:
    if not script or not whisper:
        return False
    if len(script) == 1 and len(whisper) == 1:
        return _close_tokens(script[0], whisper[0])
    concat_s = "".join(script)
    concat_w = "".join(whisper)
    if _close_tokens(concat_s, concat_w):
        return True
    if len(whisper) == 1 and whisper[0].isdigit():
        parsed = _parse_tr_int(script)
        if parsed is not None and parsed == int(whisper[0]):
            return True
    if len(script) == 1 and script[0].isdigit() and len(whisper) > 1:
        parsed = _parse_tr_int(whisper)
        if parsed is not None and parsed == int(script[0]):
            return True
    return False


def _align_indices(script: list[str], whisper: list[str]) -> list[tuple[int, int] | None]:
    n = len(script)
    m = len(whisper)
    gap = 1
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    ptr: list[list[tuple[int, int, int]]] = [[(0, 0, 0)] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        dp[i][0] = i * gap
        ptr[i][0] = (1, 1, 0)
    for j in range(1, m + 1):
        dp[0][j] = j * gap
        ptr[0][j] = (2, 0, 1)
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            best = dp[i - 1][j] + gap
            choice = (1, 1, 0)
            left = dp[i][j - 1] + gap
            if left < best:
                best = left
                choice = (2, 0, 1)
            for si in range(1, min(3, i) + 1):
                for wj in range(1, min(2, j) + 1):
                    if not _group_equivalent(script[i - si : i], whisper[j - wj : j]):
                        continue
                    cost = dp[i - si][j - wj]
                    if cost < best:
                        best = cost
                        choice = (3, si, wj)
            dp[i][j] = best
            ptr[i][j] = choice
    mapping: list[tuple[int, int] | None] = [None] * n
    i, j = n, m
    while i > 0 or j > 0:
        if i == 0:
            j -= 1
            continue
        if j == 0:
            i -= 1
            continue
        kind, si, wj = ptr[i][j]
        if kind == 3:
            start = j - wj
            end = j
            for offset in range(si):
                mapping[i - si + offset] = (start, end)
            i -= si
            j -= wj
        elif kind == 1:
            i -= 1
        else:
            j -= 1
    return mapping


def _expand_whisper_words(whisper_words: list[WhisperWord]) -> list[WhisperWord]:
    expanded: list[WhisperWord] = []
    splitter = re.compile(r"['’\-]")
    for item in whisper_words:
        parts = [part for part in splitter.split(item.word) if part.strip()]
        if len(parts) <= 1:
            expanded.append(item)
            continue
        span = max(item.end - item.start, 0.04)
        step = span / len(parts)
        for offset, part in enumerate(parts):
            expanded.append(
                WhisperWord(
                    word=part,
                    start=round(item.start + offset * step, 4),
                    end=round(item.start + (offset + 1) * step, 4),
                )
            )
    return expanded


def _repair_monotonic_times(
    tokens: list[AlignedToken], whisper_words: list[WhisperWord]
) -> list[AlignedToken]:
    """Drop matches that jump to a later repeated Whisper span; rematch locally."""
    ordered = sorted(whisper_words, key=lambda item: item.start)
    last_end = 0.0
    repaired: list[AlignedToken] = []
    for index, token in enumerate(tokens):
        keep = False
        if (
            token.status == "matched"
            and token.start is not None
            and token.end is not None
            and token.start >= last_end - 0.12
            and (index == 0 or token.start <= last_end + 10.0)
        ):
            keep = True
        if keep:
            repaired.append(token)
            last_end = float(token.end)
            continue
        window_end = last_end + 14.0
        folded = fold_token(token.text)
        hit = None
        for item in ordered:
            if item.start < last_end - 0.08:
                continue
            if item.start > window_end:
                break
            if _close_tokens(folded, fold_token(item.word)):
                hit = item
                break
        if hit is None:
            repaired.append(
                AlignedToken(text=token.text, scene_id=token.scene_id, status="unmatched")
            )
            continue
        repaired.append(
            AlignedToken(
                text=token.text,
                scene_id=token.scene_id,
                start=hit.start,
                end=hit.end,
                whisper_match=hit.word,
                status="matched",
                timing_source="whisper",
            )
        )
        last_end = hit.end
    return repaired


def align_script_to_whisper(
    plan: ScenePlan,
    whisper_words: list[WhisperWord],
    *,
    language: str | None,
    threshold: float = ALIGNMENT_MATCH_THRESHOLD,
    require_quality: bool = True,
    audio_duration: float | None = None,
    chunk_windows: list[ChunkAudioWindow] | None = None,
) -> AlignmentReport:
    script = _script_tokens(plan)
    script_norm = [fold_token(word) for word, _ in script]
    whisper_words = _expand_whisper_words(whisper_words)
    whisper_norm = [fold_token(item.word) for item in whisper_words]
    mapping = _align_indices(script_norm, whisper_norm)
    tokens: list[AlignedToken] = []
    matched = 0

    def _window_for(word_index: int) -> ChunkAudioWindow | None:
        if not chunk_windows:
            return None
        for window in chunk_windows:
            if window.word_start <= word_index < window.word_end:
                return window
        return None

    for index, ((text, scene_id), span) in enumerate(zip(script, mapping, strict=True)):
        window = _window_for(index)
        if span is None or span[0] >= len(whisper_words) or span[1] > len(whisper_words):
            tokens.append(AlignedToken(text=text, scene_id=scene_id, status="unmatched"))
            continue
        hits = whisper_words[span[0] : span[1]]
        if not hits:
            tokens.append(AlignedToken(text=text, scene_id=scene_id, status="unmatched"))
            continue
        hit_start = hits[0].start
        hit_end = hits[-1].end
        siblings = [idx for idx, item in enumerate(mapping) if item == span]
        if len(siblings) > 1:
            order = siblings.index(index)
            step = max(hit_end - hit_start, 0.04) / len(siblings)
            hit_start = round(hits[0].start + order * step, 4)
            hit_end = round(hits[0].start + (order + 1) * step, 4)
        if window is not None:
            slack = 0.35
            if hit_start < window.audio_start - slack or hit_end > window.audio_end + slack:
                tokens.append(AlignedToken(text=text, scene_id=scene_id, status="unmatched"))
                continue
        tokens.append(
            AlignedToken(
                text=text,
                scene_id=scene_id,
                start=hit_start,
                end=hit_end,
                whisper_match=" ".join(item.word for item in hits),
                status="matched",
                timing_source="whisper",
            )
        )
        matched += 1

    tokens = _repair_monotonic_times(tokens, whisper_words)
    matched = sum(1 for token in tokens if token.status == "matched")

    interpolated = 0
    index = 0
    while index < len(tokens):
        if tokens[index].status != "unmatched":
            index += 1
            continue
        start = index
        while index < len(tokens) and tokens[index].status == "unmatched":
            index += 1
        gap = tokens[start:index]
        prev_t = tokens[start - 1] if start > 0 else None
        next_t = tokens[index] if index < len(tokens) else None
        if (
            prev_t is not None
            and next_t is not None
            and prev_t.status == "matched"
            and next_t.status == "matched"
            and prev_t.end is not None
            and next_t.start is not None
            and next_t.start >= prev_t.end
            and len(gap) <= 8
        ):
            step = max(float(next_t.start) - float(prev_t.end), 0.04) / len(gap)
            for offset, token in enumerate(gap):
                tokens[start + offset] = token.model_copy(
                    update={
                        "start": round(float(prev_t.end) + offset * step, 4),
                        "end": round(float(prev_t.end) + (offset + 1) * step, 4),
                        "status": "interpolated",
                        "interpolated": True,
                        "timing_source": "interpolated_gap",
                    }
                )
                interpolated += 1

    canonical = len(tokens)
    fraction = matched / canonical if canonical else 0.0

    trailing = 0
    leading = 0
    spoken_end = None
    if whisper_words:
        spoken_end = max(item.end for item in whisper_words)
    if audio_duration is not None:
        spoken_end = max(spoken_end or 0.0, float(audio_duration) - 0.02)

    first_timed = next((i for i, item in enumerate(tokens) if item.start is not None), None)
    if first_timed is not None and first_timed > 0 and first_timed <= 6:
        lead = tokens[:first_timed]
        if all(item.status == "unmatched" for item in lead):
            end_at = float(tokens[first_timed].start or 0.0)
            span = max(end_at, 0.04)
            step = span / first_timed
            for offset, token in enumerate(lead):
                tokens[offset] = token.model_copy(
                    update={
                        "start": round(offset * step, 4),
                        "end": round((offset + 1) * step, 4),
                        "status": "interpolated",
                        "interpolated": True,
                        "timing_source": "leading_interpolation",
                    }
                )
                interpolated += 1
                leading += 1

    last_timed = next(
        (i for i, item in reversed(list(enumerate(tokens))) if item.end is not None),
        None,
    )
    if (
        last_timed is not None
        and last_timed < len(tokens) - 1
        and spoken_end is not None
        and fraction >= 0.90
    ):
        trail = tokens[last_timed + 1 :]
        if len(trail) <= 8 and all(item.status == "unmatched" for item in trail):
            start_at = float(tokens[last_timed].end or 0.0)
            remain = max(float(spoken_end) - start_at, 0.04)
            step = remain / len(trail)
            for offset, token in enumerate(trail):
                index = last_timed + 1 + offset
                tokens[index] = token.model_copy(
                    update={
                        "start": round(start_at + offset * step, 4),
                        "end": round(start_at + (offset + 1) * step, 4),
                        "status": "interpolated",
                        "interpolated": True,
                        "timing_source": "trailing_interpolation",
                    }
                )
                interpolated += 1
                trailing += 1

    unmatched = sum(1 for token in tokens if token.status == "unmatched")
    report = AlignmentReport(
        project_id=plan.project_id,
        language=language,
        canonical_word_count=canonical,
        matched_word_count=matched,
        interpolated_word_count=interpolated,
        unmatched_word_count=unmatched,
        trailing_unmatched_count=trailing,
        leading_unmatched_count=leading,
        match_fraction=round(fraction, 6),
        tokens=tokens,
        quality_passed=fraction >= threshold,
    )
    if require_quality and not report.quality_passed:
        raise AlignmentQualityError(
            f"Alignment match fraction {report.match_fraction:.3f} "
            f"is below {threshold:.2f} ({matched}/{canonical} matched)."
        )
    return report
