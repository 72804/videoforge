from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


class FFmpegError(RuntimeError):
    """FFmpeg/ffprobe failed or a required filter is missing."""


_FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "/Library/Fonts/Arial.ttf",
    "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
)


@dataclass(frozen=True)
class ProbeInfo:
    duration: float
    width: int | None
    height: int | None
    fps: float | None
    video_codec: str | None
    pixel_format: str | None
    audio_codec: str | None
    sample_rate: int | None
    channels: int | None
    has_video: bool
    has_audio: bool


_FFMPEG_FULL_BINS = (
    Path("/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg"),
    Path("/usr/local/opt/ffmpeg-full/bin/ffmpeg"),
)


def _existing_ffmpeg_candidates() -> list[Path]:
    candidates: list[Path] = []
    env = os.environ.get("DOCPROD_FFMPEG")
    if env:
        candidates.append(Path(env))
    candidates.extend(_FFMPEG_FULL_BINS)
    which = shutil.which("ffmpeg")
    if which:
        candidates.append(Path(which))
    unique: list[Path] = []
    seen: set[str] = set()
    for item in candidates:
        if not item.is_file():
            continue
        key = str(item.resolve())
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _binary_has_filter(binary: str, name: str) -> bool:
    completed = subprocess.run(
        [binary, "-hide_banner", "-filters"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return False
    for line in completed.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == name:
            return True
    return False


@lru_cache
def ffmpeg_path() -> str:
    existing = _existing_ffmpeg_candidates()
    if not existing:
        raise FFmpegError(
            "ffmpeg not found. Install FFmpeg with libass (Homebrew: ffmpeg-full) "
            "or set DOCPROD_FFMPEG to that binary."
        )
    for item in existing:
        if _binary_has_filter(str(item), "subtitles"):
            return str(item)
    return str(existing[0])


@lru_cache
def ffprobe_path() -> str:
    env = os.environ.get("DOCPROD_FFPROBE")
    if env and Path(env).is_file():
        return env
    sibling = Path(ffmpeg_path()).with_name("ffprobe")
    if sibling.is_file():
        return str(sibling)
    path = shutil.which("ffprobe")
    if not path:
        raise FFmpegError("ffprobe not found on PATH")
    return path


@lru_cache
def discover_font() -> Path:
    for candidate in _FONT_CANDIDATES:
        path = Path(candidate)
        if path.is_file():
            return path
    raise FFmpegError(
        "No usable system font found for drawtext/subtitles. "
        "Install a Unicode TTF such as Arial or DejaVu Sans."
    )


@lru_cache
def ffmpeg_has_filter(name: str) -> bool:
    return _binary_has_filter(ffmpeg_path(), name)


def require_subtitles_filter() -> None:
    if not ffmpeg_has_filter("subtitles"):
        raise FFmpegError(
            "This FFmpeg build has no 'subtitles' filter (libass). "
            "Cannot burn-in captions. Install Homebrew ffmpeg-full "
            "(libass + drawtext) or set DOCPROD_FFMPEG to that binary."
        )


def require_perspective_filter() -> None:
    if not ffmpeg_has_filter("perspective"):
        raise FFmpegError(
            "This FFmpeg build has no 'perspective' filter. "
            "Cannot apply subpixel camera motion. Install Homebrew ffmpeg-full "
            "or set DOCPROD_FFMPEG to that binary."
        )


def run_ffmpeg(args: list[str], *, timeout: int = 120) -> None:
    command = [ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y", *args]
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if completed.returncode != 0:
        raise FFmpegError(
            f"ffmpeg failed ({completed.returncode}): {completed.stderr.strip()[-2000:]}"
        )


def probe_media(path: Path) -> ProbeInfo:
    return _cached_probe_media(path)


_PROBE_LOCK = threading.Lock()
_PROBE_CACHE: dict[tuple[str, int, int], ProbeInfo] = {}


def _cached_probe_media(path: Path) -> ProbeInfo:
    stat = path.stat()
    key = (str(path.resolve()), stat.st_size, int(stat.st_mtime_ns))
    with _PROBE_LOCK:
        hit = _PROBE_CACHE.get(key)
    if hit is not None:
        return hit
    info = _probe_media_uncached(path)
    with _PROBE_LOCK:
        _PROBE_CACHE[key] = info
    return info


def _probe_media_uncached(path: Path) -> ProbeInfo:
    completed = subprocess.run(
        [
            ffprobe_path(),
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise FFmpegError(f"ffprobe failed for {path}: {completed.stderr.strip()}")
    payload = json.loads(completed.stdout)
    duration = float(payload.get("format", {}).get("duration") or 0.0)
    video = next((s for s in payload.get("streams", []) if s.get("codec_type") == "video"), None)
    audio = next((s for s in payload.get("streams", []) if s.get("codec_type") == "audio"), None)
    fps = None
    if video and video.get("avg_frame_rate") not in (None, "0/0"):
        num, _, den = video["avg_frame_rate"].partition("/")
        try:
            fps = float(num) / float(den or "1")
        except ValueError:
            fps = None
    return ProbeInfo(
        duration=duration,
        width=int(video["width"]) if video and video.get("width") else None,
        height=int(video["height"]) if video and video.get("height") else None,
        fps=fps,
        video_codec=video.get("codec_name") if video else None,
        pixel_format=video.get("pix_fmt") if video else None,
        audio_codec=audio.get("codec_name") if audio else None,
        sample_rate=int(audio["sample_rate"]) if audio and audio.get("sample_rate") else None,
        channels=int(audio["channels"]) if audio and audio.get("channels") else None,
        has_video=video is not None,
        has_audio=audio is not None,
    )


def _version_line(binary: str) -> str | None:
    completed = subprocess.run(
        [binary, "-version"],
        check=False,
        capture_output=True,
        text=True,
    )
    output = completed.stdout or completed.stderr
    return output.splitlines()[0].strip() if output else None


def ffmpeg_version_line() -> str | None:
    try:
        return _version_line(ffmpeg_path())
    except FFmpegError:
        return None


def ffprobe_version_line() -> str | None:
    try:
        return _version_line(ffprobe_path())
    except FFmpegError:
        return None


def escape_filter_path(path: Path) -> str:
    text = path.resolve().as_posix()
    return text.replace("\\", "\\\\").replace(":", "\\:").replace("'", r"\'")


def escape_drawtext(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", r"\'")
        .replace("%", "%%")
    )
