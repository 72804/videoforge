from __future__ import annotations

from dataclasses import dataclass, field

from docprod.exceptions import IntegrityBlockedError

WPM_SANITY_MIN = 75.0
WPM_SANITY_MAX = 190.0
RELATIVE_DURATION_FAIL = 1.8
RELATIVE_DURATION_WARN = 1.35
MASTER_DURATION_FAIL = 1.32
MASTER_DURATION_WARN = 1.18
WHISPER_USD_PER_MINUTE = 0.006


def words_per_minute(word_count: int, duration: float) -> float:
    if duration <= 0.01:
        return 0.0
    return word_count / (duration / 60.0)


@dataclass
class TTSChunkIntegrityResult:
    chunk_id: str
    word_count: int
    character_count: int
    duration: float
    wpm: float
    duration_per_word: float
    expected_duration: float | None
    duration_ratio: float | None
    status: str
    reasons: list[str] = field(default_factory=list)
    sibling_median_wpm: float | None = None
    recovery_actions: list[str] = field(default_factory=list)

    def blocks_master(self) -> bool:
        return self.status in {"FAIL", "SUSPICIOUS"}


def evaluate_chunk_integrity(
    *,
    chunk_id: str,
    word_count: int,
    character_count: int,
    duration: float,
    prior_wpm: list[float] | None = None,
    expected_wpm: float | None = None,
) -> TTSChunkIntegrityResult:
    wpm = words_per_minute(word_count, duration)
    dpw = duration / max(word_count, 1)
    median = None
    if prior_wpm:
        ordered = sorted(prior_wpm)
        median = ordered[len(ordered) // 2]
    pace = expected_wpm or median
    expected = (word_count / pace * 60.0) if pace and pace > 1 else None
    ratio = (duration / expected) if expected and expected > 0 else None
    reasons: list[str] = []
    status = "PASS"
    if duration >= 8.0 and (wpm < WPM_SANITY_MIN or wpm > WPM_SANITY_MAX):
        reasons.append(
            f"wpm {wpm:.1f} outside documentary sanity "
            f"{WPM_SANITY_MIN:.0f}-{WPM_SANITY_MAX:.0f}"
        )
        status = "SUSPICIOUS"
    if ratio is not None and ratio >= RELATIVE_DURATION_WARN:
        reasons.append(f"duration {ratio:.2f}x expected from sibling/project pace")
        status = "SUSPICIOUS"
    fail_relative = ratio is not None and ratio >= RELATIVE_DURATION_FAIL
    fail_slow = wpm < WPM_SANITY_MIN and (ratio or 1.0) >= 1.5
    if fail_relative or fail_slow or wpm < 55:
        status = "FAIL"
        reasons.append("speech-rate anomaly consistent with restart/repeat")
    actions = []
    if status != "PASS":
        actions = ["RETRY_CHUNK", "LOCAL_TRIM_CONFIRMED_DUPLICATE", "MANUAL_REVIEW"]
    return TTSChunkIntegrityResult(
        chunk_id=chunk_id,
        word_count=word_count,
        character_count=character_count,
        duration=duration,
        wpm=round(wpm, 3),
        duration_per_word=round(dpw, 4),
        expected_duration=round(expected, 3) if expected else None,
        duration_ratio=round(ratio, 3) if ratio else None,
        status=status,
        reasons=reasons,
        sibling_median_wpm=round(median, 3) if median else None,
        recovery_actions=actions,
    )


@dataclass
class MasterDurationCheck:
    canonical_word_count: int
    actual_duration: float
    expected_duration: float
    ratio: float
    status: str
    reasons: list[str] = field(default_factory=list)

    def blocks_whisper(self) -> bool:
        return self.status == "FAIL"


def evaluate_master_duration(
    *,
    canonical_word_count: int,
    actual_duration: float,
    observed_wpm: float,
) -> MasterDurationCheck:
    expected = canonical_word_count / max(observed_wpm, 1.0) * 60.0
    ratio = actual_duration / expected if expected else 0.0
    status = "PASS"
    reasons: list[str] = []
    if ratio >= MASTER_DURATION_WARN:
        status = "SUSPICIOUS"
        reasons.append("master longer than expected narration duration")
    if ratio >= MASTER_DURATION_FAIL:
        status = "FAIL"
        reasons.append("master implausibly long; refuse paid Whisper")
    return MasterDurationCheck(
        canonical_word_count=canonical_word_count,
        actual_duration=round(actual_duration, 3),
        expected_duration=round(expected, 3),
        ratio=round(ratio, 3),
        status=status,
        reasons=reasons,
    )


def assert_promotable(results: list[TTSChunkIntegrityResult]) -> None:
    blocked = [item for item in results if item.blocks_master()]
    if blocked:
        detail = "; ".join(f"{item.chunk_id}={item.status}" for item in blocked)
        raise IntegrityBlockedError(
            f"TTS chunks are not promotable to master.wav ({detail})."
        )
