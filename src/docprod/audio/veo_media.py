from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from docprod.providers.pricing import VEO_RETIME_RATIO_MAX
from docprod.render.ffmpeg import ffmpeg_path, probe_media, run_ffmpeg
from docprod.storage.json_store import save_json


@dataclass
class SyncAudioQC:
    accepted: bool
    clipping: bool
    missing: bool
    speech_like: bool
    music_like: bool
    reasons: list[str]


def extract_provider_audio(video: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp.wav")
    try:
        run_ffmpeg(
            ["-i", str(video), "-vn", "-ac", "2", "-ar", "48000", "-c:a", "pcm_s16le", str(tmp)],
            timeout=120,
        )
        tmp.replace(dest)
    finally:
        tmp.unlink(missing_ok=True)


def mute_and_normalize_visual(
    video: Path,
    dest: Path,
    *,
    duration: float,
    generated_seconds: float = 8.0,
) -> float:
    dest.parent.mkdir(parents=True, exist_ok=True)
    ratio = duration / generated_seconds if generated_seconds else 1.0
    if ratio > VEO_RETIME_RATIO_MAX:
        raise RuntimeError(
            f"Required/generated ratio {ratio:.3f} exceeds {VEO_RETIME_RATIO_MAX}"
        )
    tmp = dest.with_suffix(".tmp.mp4")
    tempo = generated_seconds / duration if duration else 1.0
    try:
        run_ffmpeg(
            [
                "-i",
                str(video),
                "-an",
                "-vf",
                f"setpts=PTS/{tempo:.6f},scale=1280:720:flags=lanczos,fps=30,format=yuv420p",
                "-t",
                f"{duration:.4f}",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-preset",
                "medium",
                "-crf",
                "20",
                str(tmp),
            ],
            timeout=180,
        )
        tmp.replace(dest)
    finally:
        tmp.unlink(missing_ok=True)
    probe = probe_media(dest)
    if probe.has_audio:
        raise RuntimeError("Visual derivative must not contain provider audio")
    return ratio


def volumedetect(path: Path) -> dict[str, float]:
    completed = subprocess.run(
        [
            ffmpeg_path(),
            "-hide_banner",
            "-i",
            str(path),
            "-af",
            "volumedetect",
            "-f",
            "null",
            "-",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    mean = -99.0
    peak = -99.0
    for line in (completed.stderr or "").splitlines():
        if "mean_volume:" in line:
            mean = float(line.split("mean_volume:")[1].split("dB")[0])
        if "max_volume:" in line:
            peak = float(line.split("max_volume:")[1].split("dB")[0])
    return {"mean": mean, "peak": peak}


def qc_sync_audio(
    path: Path,
    *,
    speech_detector=None,
) -> SyncAudioQC:
    reasons: list[str] = []
    if not path.is_file():
        return SyncAudioQC(False, False, True, False, False, ["missing"])
    probe = probe_media(path)
    if not probe.has_audio or probe.duration < 0.4:
        return SyncAudioQC(False, False, True, False, False, ["empty"])
    volumes = volumedetect(path)
    clipping = volumes["peak"] >= -0.2
    music_like = volumes["mean"] > -16.0
    speech_like = bool(speech_detector(path)) if speech_detector is not None else False
    if clipping:
        reasons.append("clipping")
    if music_like:
        reasons.append("excessive_music")
    if speech_like:
        reasons.append("unexpected_dialogue")
    accepted = not clipping and not music_like and not speech_like
    return SyncAudioQC(accepted, clipping, False, speech_like, music_like, reasons)


def write_candidate_meta(path: Path, payload: dict) -> None:
    save_json(path, payload)
