from __future__ import annotations

from pathlib import Path

from docprod.render.ffmpeg import probe_media, run_ffmpeg
from docprod.storage.hashing import content_hash, file_sha256
from docprod.storage.json_store import load_json, save_json


def should_copy_video_stream(path: Path, *, width: int = 1280, height: int = 720) -> bool:
    probe = probe_media(path)
    return (
        probe.has_video
        and probe.video_codec in {"h264", "avc1"}
        and probe.pixel_format in {"yuv420p", "yuvj420p"}
        and (probe.width is None or probe.width == width)
        and (probe.height is None or probe.height == height)
    )


def mux_audio_copy_video(video: Path, audio: Path, dest: Path) -> None:
    if not should_copy_video_stream(video):
        raise ValueError(f"Video stream is not copy-compatible: {video}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp.mp4")
    try:
        run_ffmpeg(
            [
                "-i",
                str(video),
                "-i",
                str(audio),
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-shortest",
                "-movflags",
                "+faststart",
                str(tmp),
            ],
            timeout=180,
        )
        tmp.replace(dest)
    finally:
        tmp.unlink(missing_ok=True)


def visual_master_hash(*, base: Path, overlay_paths: list[Path], captions: Path | None) -> str:
    parts = {
        "base": file_sha256(base) if base.is_file() else "",
        "overlays": [file_sha256(path) for path in overlay_paths if path.is_file()],
        "captions": file_sha256(captions) if captions and captions.is_file() else "",
    }
    return content_hash(parts)


def load_cached_master(meta_path: Path, expected_hash: str, dest: Path) -> bool:
    if not meta_path.is_file() or not dest.is_file():
        return False
    try:
        payload = load_json(meta_path)
    except (OSError, ValueError):
        return False
    return isinstance(payload, dict) and payload.get("hash") == expected_hash


def write_master_meta(meta_path: Path, digest: str, dest: Path) -> None:
    save_json(meta_path, {"hash": digest, "path": str(dest), "sha256": file_sha256(dest)})
