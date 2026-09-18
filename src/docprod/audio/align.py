from __future__ import annotations

from docprod.audio.models import (
    ALIGNMENT_MATCH_THRESHOLD,
    AlignedToken,
    AlignmentReport,
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


def _align_indices(script: list[str], whisper: list[str]) -> list[int | None]:
    n = len(script)
    m = len(whisper)
    gap = 1
    mismatch = 1
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    ptr = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        dp[i][0] = i * gap
        ptr[i][0] = 1
    for j in range(1, m + 1):
        dp[0][j] = j * gap
        ptr[0][j] = 2
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            diag = dp[i - 1][j - 1] + (0 if script[i - 1] == whisper[j - 1] else mismatch)
            up = dp[i - 1][j] + gap
            left = dp[i][j - 1] + gap
            best, choice = diag, 3
            if up < best:
                best, choice = up, 1
            if left < best:
                best, choice = left, 2
            dp[i][j] = best
            ptr[i][j] = choice
    mapping: list[int | None] = [None] * n
    i, j = n, m
    while i > 0 or j > 0:
        choice = ptr[i][j]
        if i == 0:
            j -= 1
            continue
        if j == 0:
            i -= 1
            continue
        if choice == 3:
            mapping[i - 1] = j - 1
            i -= 1
            j -= 1
        elif choice == 1:
            i -= 1
        else:
            j -= 1
    return mapping


def align_script_to_whisper(
    plan: ScenePlan,
    whisper_words: list[WhisperWord],
    *,
    language: str | None,
    threshold: float = ALIGNMENT_MATCH_THRESHOLD,
    require_quality: bool = True,
) -> AlignmentReport:
    script = _script_tokens(plan)
    script_norm = [fold_token(word) for word, _ in script]
    whisper_norm = [fold_token(item.word) for item in whisper_words]
    mapping = _align_indices(script_norm, whisper_norm)
    tokens: list[AlignedToken] = []
    matched = 0
    for index, ((text, scene_id), whisper_index) in enumerate(zip(script, mapping, strict=True)):
        if (
            whisper_index is None
            or whisper_index >= len(whisper_norm)
            or script_norm[index] != whisper_norm[whisper_index]
        ):
            tokens.append(AlignedToken(text=text, scene_id=scene_id, status="unmatched"))
            continue
        hit = whisper_words[whisper_index]
        tokens.append(
            AlignedToken(
                text=text,
                scene_id=scene_id,
                start=hit.start,
                end=hit.end,
                whisper_match=hit.word,
                status="matched",
            )
        )
        matched += 1

    interpolated = 0
    for index, token in enumerate(tokens):
        if token.status != "unmatched":
            continue
        if index == 0 or index == len(tokens) - 1:
            continue
        prev_t = tokens[index - 1]
        next_t = tokens[index + 1]
        if prev_t.status != "matched" or next_t.status != "matched":
            continue
        if prev_t.end is None or next_t.start is None:
            continue
        mid_start = float(prev_t.end)
        mid_end = float(next_t.start)
        if mid_end < mid_start:
            continue
        tokens[index] = token.model_copy(
            update={
                "start": round(mid_start, 4),
                "end": round(mid_end, 4),
                "status": "interpolated",
                "interpolated": True,
            }
        )
        interpolated += 1

    canonical = len(tokens)
    fraction = matched / canonical if canonical else 0.0
    report = AlignmentReport(
        project_id=plan.project_id,
        language=language,
        canonical_word_count=canonical,
        matched_word_count=matched,
        interpolated_word_count=interpolated,
        unmatched_word_count=sum(1 for token in tokens if token.status == "unmatched"),
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
