from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image

from docprod.render.ffmpeg import FFmpegError, probe_media, run_ffmpeg
from docprod.render.still import still_fit_filter
from docprod.stock.base import StockVideoProvider
from docprod.stock.models import StockVideoFile
from docprod.storage.hashing import file_sha256
from docprod.storage.json_store import atomic_write_bytes


def download_file(provider: StockVideoProvider, url: str, dest: Path) -> str:
    payload = provider.fetch_bytes(url)
    atomic_write_bytes(dest, payload)
    return file_sha256(dest)


def pick_clip_start(
    *,
    source_duration: float,
    needed: float,
    seed: int,
    scene_id: str,
    margin: float = 0.25,
) -> float:
    usable = source_duration - needed
    if usable < 0:
        raise ValueError("source too short for scene duration")
    if usable <= 2 * margin:
        return max(0.0, usable / 2)
    span = usable - 2 * margin
    digest = hashlib.sha256(f"{seed}:{scene_id}:stock-clip".encode()).digest()
    offset = int.from_bytes(digest[:4], "big") / 2**32
    return round(margin + offset * span, 3)


def mean_luma_at(path: Path, timestamp: float) -> float:
    tmp = path.with_suffix(".luma.jpg")
    try:
        run_ffmpeg(
            [
                "-ss",
                f"{timestamp:.3f}",
                "-i",
                str(path),
                "-frames:v",
                "1",
                "-q:v",
                "4",
                str(tmp),
            ],
            timeout=30,
        )
        image = Image.open(tmp).convert("L")
        hist = image.histogram()
        total = sum(hist) or 1
        return sum(index * count for index, count in enumerate(hist)) / total
    finally:
        tmp.unlink(missing_ok=True)


def adjust_start_away_from_black(
    path: Path,
    start: float,
    needed: float,
    source_duration: float,
) -> float:
    current = start
    for _ in range(6):
        end = current + needed
        if end > source_duration:
            break
        try:
            first = mean_luma_at(path, current + 0.04)
            last = mean_luma_at(path, max(current, end - 0.08))
        except (FFmpegError, OSError):
            return current
        if first >= 12 and last >= 12:
            return current
        current = min(current + 0.2, max(0.0, source_duration - needed))
    return current


def normalize_stock_clip(
    source: Path,
    dest: Path,
    *,
    start: float,
    duration: float,
    width: int = 1280,
    height: int = 720,
    fps: int = 30,
) -> str:
    probe = probe_media(source)
    src_w = probe.width or width
    src_h = probe.height or height
    fit = still_fit_filter(src_w, src_h, width, height)
    vf = f"{fit},fps={fps},format=yuv420p"
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp.mp4")
    try:
        run_ffmpeg(
            [
                "-ss",
                f"{start:.3f}",
                "-i",
                str(source),
                "-t",
                f"{duration:.4f}",
                "-map",
                "0:v:0",
                "-an",
                "-dn",
                "-sn",
                "-vf",
                vf,
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-preset",
                "veryfast",
                "-crf",
                "20",
                str(tmp),
            ],
            timeout=180,
        )
        tmp.replace(dest)
    finally:
        tmp.unlink(missing_ok=True)
    return file_sha256(dest)


def rendition_payload(file: StockVideoFile) -> dict[str, object]:
    return {
        "file_id": file.file_id,
        "quality": file.quality,
        "file_type": file.file_type,
        "width": file.width,
        "height": file.height,
        "fps": file.fps,
        "link": file.link,
    }
