from __future__ import annotations

import math
import re

from docprod.models.script import TIMING_TOLERANCE, NarrationScript, Utterance, WordTiming
from docprod.planning.models import VisualBeat, round_time, times_touch
from docprod.planning.profile import ScenePlannerProfile

_STRONG_PUNCT = re.compile(r"[.!?…;:]$")
_WEAK_PUNCT = re.compile(r"[,]$")


def segment_script(script: NarrationScript, profile: ScenePlannerProfile) -> list[VisualBeat]:
    """Turn timed utterances into contiguous visual beats (planner policy)."""
    if not script.utterances:
        return []
    beats: list[VisualBeat] = []
    for utterance in script.utterances:
        beats.extend(_segment_utterance(utterance, profile))
    beats = _fill_gaps(beats, profile)
    beats = _merge_short_beats(beats, profile)
    return _snap_contiguous(beats)


def _segment_utterance(utterance: Utterance, profile: ScenePlannerProfile) -> list[VisualBeat]:
    duration = utterance.end - utterance.start
    if duration <= profile.max_scene_duration + TIMING_TOLERANCE:
        return [
            VisualBeat(
                start=round_time(utterance.start),
                end=round_time(utterance.end),
                text=utterance.text.strip(),
                source_utterance_ids=[utterance.id],
                segmentation_reason="keep_utterance",
            )
        ]
    if utterance.words:
        return _split_with_words(utterance, profile)
    return _split_proportional(utterance, profile)


def _chunk_count(duration: float, profile: ScenePlannerProfile) -> int:
    n = max(2, int(round(duration / profile.target_scene_duration)))
    while duration / n > profile.max_scene_duration + TIMING_TOLERANCE:
        n += 1
    while (
        n > 1
        and duration / n < profile.min_scene_duration - TIMING_TOLERANCE
        and duration / (n - 1) <= profile.max_scene_duration + TIMING_TOLERANCE
    ):
        n -= 1
    return n


def _split_with_words(utterance: Utterance, profile: ScenePlannerProfile) -> list[VisualBeat]:
    words = utterance.words
    remaining_start = utterance.start
    remaining_index = 0
    chunks: list[VisualBeat] = []
    while remaining_start < utterance.end - TIMING_TOLERANCE:
        remaining = utterance.end - remaining_start
        if remaining <= profile.max_scene_duration + TIMING_TOLERANCE:
            text = _text_from_words(words, remaining_index, len(words), utterance.text)
            chunks.append(
                VisualBeat(
                    start=round_time(remaining_start),
                    end=round_time(utterance.end),
                    text=text,
                    source_utterance_ids=[utterance.id],
                    segmentation_reason=(
                        "split_long_utterance_remainder"
                        if chunks
                        else "keep_utterance"
                    ),
                )
            )
            break
        target_end = remaining_start + profile.target_scene_duration
        max_end = min(utterance.end, remaining_start + profile.max_scene_duration)
        min_end = remaining_start + profile.min_scene_duration
        split_at, reason, word_end_index = _choose_word_split(
            words,
            remaining_index,
            remaining_start,
            target_end,
            min_end,
            max_end,
            utterance.end,
        )
        text = _text_from_words(words, remaining_index, word_end_index, utterance.text)
        chunks.append(
            VisualBeat(
                start=round_time(remaining_start),
                end=round_time(split_at),
                text=text,
                source_utterance_ids=[utterance.id],
                segmentation_reason=reason,
            )
        )
        remaining_start = split_at
        remaining_index = word_end_index
    return chunks


def _choose_word_split(
    words: list[WordTiming],
    start_index: int,
    chunk_start: float,
    target_end: float,
    min_end: float,
    max_end: float,
    utterance_end: float,
) -> tuple[float, str, int]:
    best_punct: tuple[float, int, int] | None = None
    best_word: tuple[float, int] | None = None
    for index in range(start_index, len(words)):
        word = words[index]
        end = word.end
        if end <= chunk_start + TIMING_TOLERANCE:
            continue
        if end > max_end + TIMING_TOLERANCE:
            break
        if end < min_end - TIMING_TOLERANCE and index > start_index:
            continue
        distance = abs(end - target_end)
        if best_word is None or distance < best_word[0] - 1e-9:
            best_word = (distance, index)
        stripped = word.word.strip()
        punct_rank = 0
        if _STRONG_PUNCT.search(stripped):
            punct_rank = 2
        elif _WEAK_PUNCT.search(stripped):
            punct_rank = 1
        if punct_rank and (best_punct is None or punct_rank > best_punct[2] or (
            punct_rank == best_punct[2] and distance < best_punct[0]
        )):
            best_punct = (distance, index, punct_rank)
    if best_punct is not None:
        index = best_punct[1]
        return words[index].end, "split_long_utterance_at_punctuation", index + 1
    if best_word is not None:
        index = best_word[1]
        return words[index].end, "split_long_utterance_at_word_boundary", index + 1
    # No eligible word inside the window: cut at max_end.
    return max_end, "split_long_utterance_at_max_duration", _index_at_or_before(words, max_end)


def _index_at_or_before(words: list[WordTiming], t: float) -> int:
    for index, word in enumerate(words):
        if word.end > t + TIMING_TOLERANCE:
            return max(index, 1)
    return len(words)


def _text_from_words(words: list[WordTiming], start_i: int, end_i: int, fallback: str) -> str:
    slice_words = words[start_i:end_i]
    if not slice_words:
        return fallback.strip()
    return " ".join(word.word for word in slice_words).strip()


def _split_proportional(utterance: Utterance, profile: ScenePlannerProfile) -> list[VisualBeat]:
    duration = utterance.end - utterance.start
    n = _chunk_count(duration, profile)
    piece = duration / n
    tokens = utterance.text.split()
    chunks: list[VisualBeat] = []
    for i in range(n):
        start = utterance.start + i * piece
        end = utterance.end if i == n - 1 else utterance.start + (i + 1) * piece
        text = _slice_tokens(tokens, i, n)
        chunks.append(
            VisualBeat(
                start=round_time(start),
                end=round_time(end),
                text=text,
                source_utterance_ids=[utterance.id],
                segmentation_reason="split_long_utterance_proportional",
            )
        )
    return chunks


def _slice_tokens(tokens: list[str], index: int, n: int) -> str:
    if not tokens:
        return ""
    start = math.floor(len(tokens) * index / n)
    end = math.floor(len(tokens) * (index + 1) / n)
    if index == n - 1:
        end = len(tokens)
    if start >= end:
        end = min(len(tokens), start + 1)
    return " ".join(tokens[start:end]).strip()


def _fill_gaps(beats: list[VisualBeat], profile: ScenePlannerProfile) -> list[VisualBeat]:
    if not beats:
        return beats
    filled: list[VisualBeat] = [beats[0]]
    for beat in beats[1:]:
        previous = filled[-1]
        gap = beat.start - previous.end
        if gap <= TIMING_TOLERANCE:
            filled.append(beat)
            continue
        if gap <= profile.short_gap_threshold + TIMING_TOLERANCE:
            previous.end = round_time(beat.start)
            previous.segmentation_reason = f"{previous.segmentation_reason};extend_across_short_gap"
            filled.append(beat)
            continue
        filled.append(
            VisualBeat(
                start=round_time(previous.end),
                end=round_time(beat.start),
                text="",
                source_utterance_ids=[],
                segmentation_reason="visual_bridge_long_gap",
                visual_bridge=True,
            )
        )
        filled.append(beat)
    return filled


def _merge_short_beats(beats: list[VisualBeat], profile: ScenePlannerProfile) -> list[VisualBeat]:
    if not beats:
        return beats
    merged = list(beats)
    changed = True
    while changed:
        changed = False
        i = 0
        while i < len(merged):
            beat = merged[i]
            if beat.duration + TIMING_TOLERANCE >= profile.min_scene_duration:
                i += 1
                continue
            prev_ok = (
                i > 0
                and (merged[i - 1].duration + beat.duration)
                <= profile.max_scene_duration + TIMING_TOLERANCE
            )
            next_ok = (
                i + 1 < len(merged)
                and (beat.duration + merged[i + 1].duration)
                <= profile.max_scene_duration + TIMING_TOLERANCE
            )
            if prev_ok:
                _absorb(merged[i - 1], beat)
                del merged[i]
                changed = True
                continue
            if next_ok:
                _absorb(beat, merged[i + 1])
                del merged[i + 1]
                changed = True
                continue
            i += 1
    return merged


def _absorb(keep: VisualBeat, other: VisualBeat) -> None:
    keep.end = round_time(other.end)
    keep.text = " ".join(part for part in (keep.text.strip(), other.text.strip()) if part)
    ids = list(keep.source_utterance_ids)
    for item in other.source_utterance_ids:
        if item not in ids:
            ids.append(item)
    keep.source_utterance_ids = ids
    keep.visual_bridge = keep.visual_bridge and other.visual_bridge
    keep.segmentation_reason = f"{keep.segmentation_reason};merged_short_beat"


def _snap_contiguous(beats: list[VisualBeat]) -> list[VisualBeat]:
    if not beats:
        return beats
    snapped: list[VisualBeat] = []
    for beat in beats:
        if snapped and beat.start < snapped[-1].end - TIMING_TOLERANCE:
            raise ValueError("internal segmentation overlap")
        if snapped and not times_touch(snapped[-1].end, beat.start):
            beat.start = snapped[-1].end
        beat.start = round_time(beat.start)
        beat.end = round_time(beat.end)
        snapped.append(beat)
    return snapped
