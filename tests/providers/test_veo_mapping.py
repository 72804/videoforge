from __future__ import annotations

from pathlib import Path

from PIL import Image

from docprod.providers.veo_mapping import assign_videos, similarity_matrix
from docprod.render.ffmpeg import run_ffmpeg


def _jpeg(path: Path, color: tuple[int, int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (128, 72), color).save(path, "JPEG")


def _color_mp4(path: Path, color: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            f"color=c={color}:s=128x72:d=0.4:r=10",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        timeout=20,
    )


def test_keyframe_mapping_unambiguous(tmp_path: Path) -> None:
    from docprod.providers.veo_mapping import extract_frame

    ka = tmp_path / "a.jpg"
    kb = tmp_path / "b.jpg"
    _jpeg(ka, (220, 20, 20))
    _jpeg(kb, (20, 20, 220))
    va = tmp_path / "va.mp4"
    vb = tmp_path / "vb.mp4"
    _color_mp4(va, "0xFF0000")
    _color_mp4(vb, "0x0000FF")
    fa = tmp_path / "fa.jpg"
    fb = tmp_path / "fb.jpg"
    extract_frame(va, fa)
    extract_frame(vb, fb)
    matrix = similarity_matrix({"v1": fa, "v2": fb}, {"au_a": ka, "au_b": kb})
    assigned = assign_videos(matrix)
    assert assigned is not None
    assert set(assigned.values()) == {"au_a", "au_b"}


def test_ambiguous_mapping_stops(tmp_path: Path) -> None:
    from docprod.providers.veo_mapping import extract_frame

    ka = tmp_path / "a.jpg"
    kb = tmp_path / "b.jpg"
    _jpeg(ka, (80, 80, 80))
    _jpeg(kb, (82, 82, 82))
    va = tmp_path / "va.mp4"
    vb = tmp_path / "vb.mp4"
    _color_mp4(va, "gray")
    _color_mp4(vb, "gray")
    fa = tmp_path / "fa.jpg"
    fb = tmp_path / "fb.jpg"
    extract_frame(va, fa)
    extract_frame(vb, fb)
    matrix = similarity_matrix({"v1": fa, "v2": fb}, {"au_a": ka, "au_b": kb})
    assert assign_videos(matrix) is None
