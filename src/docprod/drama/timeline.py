from __future__ import annotations

from pathlib import Path

from docprod.audio.models import (
    AlignmentReport,
    RuntimeSceneTiming,
    RuntimeTimeline,
)
from docprod.drama.planner import TITLE_SECONDS
from docprod.models.scene import ScenePlan
from docprod.render.ffmpeg import probe_media, run_ffmpeg


def spoken_scene_plan(plan: ScenePlan) -> ScenePlan:
    spoken = [scene for scene in plan.scenes if scene.narration.strip()]
    if not spoken:
        raise ValueError("Drama plan has no spoken scenes")
    return plan.model_copy(update={"scenes": spoken, "total_duration": spoken[-1].end})


def is_title_card(scene) -> bool:
    return bool((scene.metadata or {}).get("cinematic_title_card"))


def insert_title_windows(
    full_plan: ScenePlan,
    spoken_timeline: RuntimeTimeline,
    *,
    audio_duration: float,
    title_seconds: float = TITLE_SECONDS,
) -> tuple[RuntimeTimeline, list[tuple[float, float]]]:
    """Insert silent title-card windows between spoken scenes without shifting speech internally.

    Returns the padded runtime timeline and silence inserts as (original_audio_time, duration).
    """
    spoken = {item.scene_id: item for item in spoken_timeline.scenes}
    inserts: list[tuple[float, float]] = []
    timings: list[RuntimeSceneTiming] = []
    pad = 0.0
    prev_end = 0.0
    for scene in full_plan.scenes:
        if is_title_card(scene):
            start = prev_end
            end = start + title_seconds
            orig = round(start - pad, 4)
            inserts.append((orig, title_seconds))
            timings.append(
                RuntimeSceneTiming(
                    scene_id=scene.id,
                    start=round(start, 4),
                    end=round(end, 4),
                    duration=round(title_seconds, 4),
                    planned_duration=float(scene.duration),
                    narration="",
                    asset_unit_id=str(scene.metadata.get("asset_unit_id") or ""),
                    runtime_strategy="title_card",
                )
            )
            pad += title_seconds
            prev_end = end
            continue
        item = spoken[scene.id]
        start = item.start + pad
        end = item.end + pad
        timings.append(
            RuntimeSceneTiming(
                scene_id=scene.id,
                start=round(start, 4),
                end=round(end, 4),
                duration=round(end - start, 4),
                planned_duration=float(scene.duration),
                narration=scene.narration,
                asset_unit_id=str(scene.metadata.get("asset_unit_id") or ""),
                runtime_strategy="ai_image",
            )
        )
        prev_end = end
    total_audio = audio_duration + pad
    if timings:
        last = timings[-1]
        if last.end < total_audio:
            timings[-1] = last.model_copy(
                update={
                    "end": round(total_audio, 4),
                    "duration": round(total_audio - last.start, 4),
                }
            )
    return (
        RuntimeTimeline(
            project_id=full_plan.project_id,
            audio_duration=round(total_audio, 4),
            total_duration=round(timings[-1].end if timings else 0.0, 4),
            scenes=timings,
        ),
        inserts,
    )


def shift_alignment(report: AlignmentReport, inserts: list[tuple[float, float]]) -> AlignmentReport:
    if not inserts:
        return report
    tokens = []
    for token in report.tokens:
        if token.start is None or token.end is None:
            tokens.append(token)
            continue
        extra = sum(duration for at, duration in inserts if token.start >= at - 1e-6)
        tokens.append(
            token.model_copy(
                update={
                    "start": round(token.start + extra, 4),
                    "end": round(token.end + extra, 4),
                }
            )
        )
    return report.model_copy(update={"tokens": tokens})


def pad_wav_with_silences(
    source: Path, dest: Path, inserts: list[tuple[float, float]]
) -> float:
    if not inserts:
        if source.resolve() != dest.resolve():
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(source.read_bytes())
        return probe_media(dest).duration
    probe = probe_media(source)
    rate = probe.sample_rate or 48000
    channels = probe.channels or 1
    layout = "mono" if channels == 1 else "stereo"
    dest.parent.mkdir(parents=True, exist_ok=True)
    work = dest.parent / ".title_pad_work"
    work.mkdir(parents=True, exist_ok=True)
    parts: list[Path] = []
    cursor = 0.0
    ordered = sorted(inserts, key=lambda item: item[0])
    try:
        for index, (at, duration) in enumerate(ordered):
            at = min(max(0.0, at), probe.duration)
            if at > cursor + 0.005:
                clip = work / f"speech_{index:02d}.wav"
                run_ffmpeg(
                    [
                        "-i",
                        str(source),
                        "-ss",
                        f"{cursor:.4f}",
                        "-to",
                        f"{at:.4f}",
                        "-ar",
                        str(rate),
                        "-ac",
                        str(channels),
                        "-c:a",
                        "pcm_s16le",
                        str(clip),
                    ],
                    timeout=120,
                )
                parts.append(clip)
            silence = work / f"silence_{index:02d}.wav"
            run_ffmpeg(
                [
                    "-f",
                    "lavfi",
                    "-i",
                    f"anullsrc=r={rate}:cl={layout}:d={duration:.4f}",
                    "-t",
                    f"{duration:.4f}",
                    "-ar",
                    str(rate),
                    "-ac",
                    str(channels),
                    "-c:a",
                    "pcm_s16le",
                    str(silence),
                ],
                timeout=60,
            )
            parts.append(silence)
            cursor = at
        if cursor < probe.duration - 0.005:
            tail = work / "speech_tail.wav"
            run_ffmpeg(
                [
                    "-i",
                    str(source),
                    "-ss",
                    f"{cursor:.4f}",
                    "-ar",
                    str(rate),
                    "-ac",
                    str(channels),
                    "-c:a",
                    "pcm_s16le",
                    str(tail),
                ],
                timeout=120,
            )
            parts.append(tail)
        listing = work / "concat.txt"
        listing.write_text(
            "".join(f"file '{path.resolve().as_posix()}'\n" for path in parts),
            encoding="utf-8",
        )
        tmp = dest.with_suffix(".tmp.wav")
        run_ffmpeg(
            [
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(listing),
                "-c",
                "copy",
                str(tmp),
            ],
            timeout=180,
        )
        tmp.replace(dest)
    finally:
        for path in work.glob("*"):
            path.unlink(missing_ok=True)
        work.rmdir()
    return probe_media(dest).duration


def title_windows(timeline: RuntimeTimeline, plan: ScenePlan) -> list[tuple[float, float]]:
    titles = {
        scene.id for scene in plan.scenes if is_title_card(scene)
    }
    return [
        (item.start, item.end) for item in timeline.scenes if item.scene_id in titles
    ]


def filter_cues_over_titles(
    cues: list[tuple[float, float, str]],
    windows: list[tuple[float, float]],
) -> list[tuple[float, float, str]]:
    kept: list[tuple[float, float, str]] = []
    for start, end, text in cues:
        mid = (start + end) / 2
        if any(window[0] - 0.02 <= mid < window[1] + 0.02 for window in windows):
            continue
        kept.append((start, end, text))
    return kept
