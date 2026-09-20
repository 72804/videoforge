from __future__ import annotations

import math
import struct
import wave
from dataclasses import dataclass, field
from pathlib import Path

from docprod.audio.models import AlignmentReport
from docprod.models.scene import ScenePlan
from docprod.quality.duration import ACT_TWO_MAX, ACT_TWO_MIN
from docprod.render.ffmpeg import FFmpegError, probe_media, run_ffmpeg
from docprod.storage.json_store import load_model
from docprod.storage.paths import ProjectPaths

B07_LINE_WORDS = ("kemal", "e", "yaz")
PRE_PAD_SECONDS = 1.5
POST_PAD_SECONDS = 2.0
COUNTDOWN_SECONDS = 3.0
ACT_TWO_ASPECT_MIN = 0.5
ACT_TWO_ASPECT_MAX = 2.358
URL_VIDEO_BYTES = 32 * 1024 * 1024
EPHEMERAL_VIDEO_BYTES = 200 * 1024 * 1024
WARN_ONSET_S = 0.120
WARN_END_S = 0.150
WARN_DURATION_S = 0.150
BLOCK_DELTA_S = 0.300
B07_REFERENCE_WAV = "b07_cedar_timing_reference.wav"
B07_REFERENCE_MP3 = "b07_cedar_timing_reference.mp3"
B07_ASSIST_WAV = "b07_recording_assist.wav"


@dataclass(frozen=True)
class DialogueSpan:
    scene_id: str
    beat_id: str
    words: tuple[str, ...]
    master_start: float
    master_end: float
    speech_duration: float
    extract_start: float
    extract_end: float
    line_rel_start: float
    line_rel_end: float
    surrounding: tuple[tuple[str, float, float], ...]


@dataclass
class MediaCheck:
    path: Path
    ok: bool
    duration: float | None = None
    video_codec: str | None = None
    width: int | None = None
    height: int | None = None
    aspect_ratio: float | None = None
    fps: float | None = None
    size_bytes: int = 0
    has_audio: bool = False
    audio_codec: str | None = None
    decodable: bool = False
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SyncCheck:
    expected_onset: float
    expected_end: float
    expected_duration: float
    measured_onset: float | None
    measured_end: float | None
    onset_delta: float | None
    end_delta: float | None
    duration_delta: float | None
    status: str
    notes: tuple[str, ...]


def scene_id_for_beat(plan: ScenePlan, beat_id: str) -> str:
    for scene in plan.scenes:
        if str((scene.metadata or {}).get("beat_id") or "") == beat_id:
            return scene.id
    raise ValueError(f"No scene with beat_id={beat_id!r}")


def find_dialogue_span(
    alignment: AlignmentReport,
    *,
    scene_id: str,
    beat_id: str,
    words: tuple[str, ...] = B07_LINE_WORDS,
    pre_pad: float = PRE_PAD_SECONDS,
    post_pad: float = POST_PAD_SECONDS,
) -> DialogueSpan:
    tokens = [t for t in alignment.tokens if t.scene_id == scene_id]
    folded = [(i, (t.text or "").casefold().strip("“”\"'.,;:")) for i, t in enumerate(tokens)]
    start_i: int | None = None
    for i, _word in folded:
        chunk = tuple(folded[j][1] for j in range(i, min(i + len(words), len(folded))))
        if chunk == words:
            start_i = i
            break
    if start_i is None:
        raise ValueError(f"Could not find {words!r} in {scene_id} alignment")
    line = tokens[start_i : start_i + len(words)]
    if any(t.start is None or t.end is None for t in line):
        raise ValueError("Aligned line is missing timestamps")
    master_start = float(line[0].start)
    master_end = float(line[-1].end)
    extract_start = max(0.0, master_start - pre_pad)
    extract_end = master_end + post_pad
    surrounding = tuple(
        (t.text, float(t.start or 0.0), float(t.end or 0.0)) for t in tokens if t.start is not None
    )
    return DialogueSpan(
        scene_id=scene_id,
        beat_id=beat_id,
        words=words,
        master_start=master_start,
        master_end=master_end,
        speech_duration=round(master_end - master_start, 6),
        extract_start=round(extract_start, 6),
        extract_end=round(extract_end, 6),
        line_rel_start=round(master_start - extract_start, 6),
        line_rel_end=round(master_end - extract_start, 6),
        surrounding=surrounding,
    )


def b07_span(paths: ProjectPaths) -> DialogueSpan:
    plan = load_model(paths.scene_plan_json, ScenePlan)
    alignment = load_model(paths.narration_alignment_json(), AlignmentReport)
    scene_id = scene_id_for_beat(plan, "b07")
    return find_dialogue_span(alignment, scene_id=scene_id, beat_id="b07")


def cut_wav(src: Path, dest: Path, start: float, duration: float) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp.wav")
    try:
        run_ffmpeg(
            [
                "-i",
                str(src),
                "-ss",
                f"{start:.6f}",
                "-t",
                f"{duration:.6f}",
                "-acodec",
                "pcm_s16le",
                "-ar",
                "48000",
                "-ac",
                "1",
                str(tmp),
            ],
            timeout=60,
        )
        tmp.replace(dest)
    finally:
        tmp.unlink(missing_ok=True)


def wav_to_mp3(src: Path, dest: Path) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp.mp3")
    try:
        run_ffmpeg(
            ["-i", str(src), "-codec:a", "libmp3lame", "-q:a", "4", str(tmp)],
            timeout=60,
        )
        tmp.replace(dest)
        return True
    except FFmpegError:
        tmp.unlink(missing_ok=True)
        try:
            run_ffmpeg(["-i", str(src), "-f", "mp3", str(tmp)], timeout=60)
            tmp.replace(dest)
            return True
        except FFmpegError:
            tmp.unlink(missing_ok=True)
            return False
    finally:
        tmp.unlink(missing_ok=True)


def build_countdown_wav(dest: Path, duration: float = COUNTDOWN_SECONDS) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp.wav")
    filt = (
        "aevalsrc=exprs='0.045*sin(2*PI*660*t)*between(t,0,0.08)"
        "+0.045*sin(2*PI*660*t)*between(t,1,1.08)"
        "+0.055*sin(2*PI*880*t)*between(t,2,2.08)'"
        f":s=48000:d={duration},"
        "aformat=sample_fmts=s16:channel_layouts=mono"
    )
    try:
        run_ffmpeg(["-filter_complex", filt, "-ac", "1", "-ar", "48000", str(tmp)], timeout=30)
        tmp.replace(dest)
    finally:
        tmp.unlink(missing_ok=True)


def concat_wavs(left: Path, right: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp.wav")
    filt = "[0:a][1:a]concat=n=2:v=0:a=1[a]"
    try:
        run_ffmpeg(
            [
                "-i",
                str(left),
                "-i",
                str(right),
                "-filter_complex",
                filt,
                "-map",
                "[a]",
                "-acodec",
                "pcm_s16le",
                "-ar",
                "48000",
                "-ac",
                "1",
                str(tmp),
            ],
            timeout=60,
        )
        tmp.replace(dest)
    finally:
        tmp.unlink(missing_ok=True)


def export_b07_reference_package(paths: ProjectPaths) -> dict[str, Path | DialogueSpan | bool]:
    span = b07_span(paths)
    master = paths.narration_master_wav()
    if not master.is_file():
        raise FileNotFoundError(master)
    review = paths.review_dir
    wav = review / B07_REFERENCE_WAV
    mp3 = review / B07_REFERENCE_MP3
    assist = review / B07_ASSIST_WAV
    duration = span.extract_end - span.extract_start
    cut_wav(master, wav, span.extract_start, duration)
    mp3_ok = wav_to_mp3(wav, mp3)
    countdown = review / "_b07_countdown.tmp.wav"
    try:
        build_countdown_wav(countdown)
        concat_wavs(countdown, wav, assist)
    finally:
        countdown.unlink(missing_ok=True)
    return {"span": span, "wav": wav, "mp3": mp3, "assist": assist, "mp3_ok": mp3_ok}


def validate_driving_video(path: Path) -> MediaCheck:
    check = MediaCheck(path=path, ok=False, size_bytes=path.stat().st_size if path.is_file() else 0)
    if not path.is_file():
        check.errors.append("file missing")
        return check
    try:
        probe = probe_media(path)
    except FFmpegError as exc:
        check.errors.append(f"not decodable: {exc}")
        return check
    check.decodable = True
    check.duration = probe.duration
    check.video_codec = probe.video_codec
    check.width = probe.width
    check.height = probe.height
    check.fps = probe.fps
    check.has_audio = probe.has_audio
    check.audio_codec = probe.audio_codec
    if probe.width and probe.height:
        check.aspect_ratio = round(probe.width / probe.height, 6)
    if not probe.has_video:
        check.errors.append("no video stream")
    if probe.duration <= 0:
        check.errors.append("duration is zero")
    if probe.duration + 1e-9 < ACT_TWO_MIN:
        check.errors.append(f"duration {probe.duration:.3f}s < Act-Two min {ACT_TWO_MIN}s")
    if probe.duration > ACT_TWO_MAX + 1e-9:
        check.errors.append(f"duration {probe.duration:.3f}s > Act-Two max {ACT_TWO_MAX}s")
    if check.aspect_ratio is not None and not (
        ACT_TWO_ASPECT_MIN - 1e-9 <= check.aspect_ratio <= ACT_TWO_ASPECT_MAX + 1e-9
    ):
        check.errors.append(
            f"aspect {check.aspect_ratio} outside Act-Two {ACT_TWO_ASPECT_MIN}–{ACT_TWO_ASPECT_MAX}"
        )
    if check.size_bytes > EPHEMERAL_VIDEO_BYTES:
        check.errors.append(f"file size {check.size_bytes} exceeds ephemeral 200MB")
    elif check.size_bytes > URL_VIDEO_BYTES:
        check.warnings.append("file > 32MB URL limit; use ephemeral upload (200MB)")
    if not probe.has_audio:
        check.warnings.append("no audio stream (timing QC cannot measure speech)")
    if probe.width and probe.height and probe.width < probe.height:
        check.warnings.append("portrait; landscape 1280:720 output is preferred")
    check.ok = not check.errors
    return check


def extract_audio_wav(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp.wav")
    try:
        run_ffmpeg(
            [
                "-i",
                str(src),
                "-vn",
                "-acodec",
                "pcm_s16le",
                "-ar",
                "16000",
                "-ac",
                "1",
                str(tmp),
            ],
            timeout=60,
        )
        tmp.replace(dest)
    finally:
        tmp.unlink(missing_ok=True)


def _pcm_mono(path: Path) -> tuple[int, list[float]]:
    with wave.open(str(path), "rb") as handle:
        sr = handle.getframerate()
        n = handle.getnframes()
        raw = handle.readframes(n)
        width = handle.getsampwidth()
        if width != 2:
            raise ValueError("expected 16-bit PCM")
    samples = struct.unpack("<" + "h" * (len(raw) // 2), raw)
    scale = 1.0 / 32768.0
    return sr, [s * scale for s in samples]


def speech_bounds(
    samples: list[float],
    sr: int,
    *,
    search_start: float,
    search_end: float,
) -> tuple[float | None, float | None]:
    hop = max(1, int(sr * 0.01))
    i0 = max(0, int(search_start * sr))
    i1 = min(len(samples), int(search_end * sr))
    if i1 - i0 < hop * 4:
        return None, None
    rms: list[tuple[float, float]] = []
    for i in range(i0, i1 - hop, hop):
        window = samples[i : i + hop]
        energy = math.sqrt(sum(x * x for x in window) / len(window))
        rms.append((i / sr, energy))
    if not rms:
        return None, None
    energies = [e for _, e in rms]
    peak = max(energies)
    median = sorted(energies)[len(energies) // 2]
    thresh = max(peak * 0.22, median * 3.0, 0.01)
    voiced = [t for t, e in rms if e >= thresh]
    if not voiced:
        return None, None
    return voiced[0], voiced[-1] + (hop / sr)


def evaluate_sync(
    *,
    expected_onset: float,
    expected_end: float,
    measured_onset: float | None,
    measured_end: float | None,
) -> SyncCheck:
    expected_duration = expected_end - expected_onset
    notes: list[str] = []
    onset_delta = None
    end_delta = None
    duration_delta = None
    if measured_onset is None or measured_end is None:
        notes.append("could not measure speech bounds locally")
        return SyncCheck(
            expected_onset=expected_onset,
            expected_end=expected_end,
            expected_duration=expected_duration,
            measured_onset=measured_onset,
            measured_end=measured_end,
            onset_delta=None,
            end_delta=None,
            duration_delta=None,
            status="unmeasured",
            notes=tuple(notes),
        )
    onset_delta = measured_onset - expected_onset
    end_delta = measured_end - expected_end
    duration_delta = (measured_end - measured_onset) - expected_duration
    abs_onset = abs(onset_delta)
    abs_end = abs(end_delta)
    abs_dur = abs(duration_delta)
    status = "ok"
    if abs_onset > WARN_ONSET_S:
        notes.append(f"onset delta {onset_delta * 1000:.0f}ms > {WARN_ONSET_S * 1000:.0f}ms")
        status = "warn"
    if abs_end > WARN_END_S:
        notes.append(f"end delta {end_delta * 1000:.0f}ms > {WARN_END_S * 1000:.0f}ms")
        status = "warn"
    if abs_dur > WARN_DURATION_S:
        notes.append(
            f"duration delta {duration_delta * 1000:.0f}ms > {WARN_DURATION_S * 1000:.0f}ms"
        )
        status = "warn"
    if max(abs_onset, abs_end, abs_dur) > BLOCK_DELTA_S:
        notes.append(f"timing delta exceeds block threshold {BLOCK_DELTA_S * 1000:.0f}ms")
        status = "block"
    if status == "ok":
        notes.append("within warn thresholds")
    return SyncCheck(
        expected_onset=expected_onset,
        expected_end=expected_end,
        expected_duration=expected_duration,
        measured_onset=measured_onset,
        measured_end=measured_end,
        onset_delta=onset_delta,
        end_delta=end_delta,
        duration_delta=duration_delta,
        status=status,
        notes=tuple(notes),
    )


def expected_line_on_clock(span: DialogueSpan, clock: str) -> tuple[float, float]:
    if clock == "assist":
        offset = COUNTDOWN_SECONDS
        return span.line_rel_start + offset, span.line_rel_end + offset
    if clock == "reference":
        return span.line_rel_start, span.line_rel_end
    raise ValueError(f"Unknown clock {clock!r}; use assist or reference")


def sync_driving_to_cedar(
    driving: Path,
    span: DialogueSpan,
    *,
    clock: str = "assist",
    work_dir: Path | None = None,
) -> SyncCheck:
    expected_onset, expected_end = expected_line_on_clock(span, clock)
    work = work_dir or driving.parent
    wav = work / f"{driving.stem}_speech.wav"
    extract_audio_wav(driving, wav)
    sr, samples = _pcm_mono(wav)
    search_pad = 0.8
    onset, end = speech_bounds(
        samples,
        sr,
        search_start=max(0.0, expected_onset - search_pad),
        search_end=expected_end + search_pad,
    )
    return evaluate_sync(
        expected_onset=expected_onset,
        expected_end=expected_end,
        measured_onset=onset,
        measured_end=end,
    )
