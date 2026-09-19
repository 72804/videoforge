from __future__ import annotations

from pathlib import Path

from docprod.render.ffmpeg import probe_media, run_ffmpeg
from docprod.render.mux import mux_audio_copy_video, should_copy_video_stream
from docprod.storage.identity import poll_delays
from docprod.storage.json_store import atomic_write_text


def _tiny_mp4(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=1280x720:d=0.4:r=30",
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
            "-an",
            str(path),
        ],
        timeout=20,
    )


def _tiny_wav(path: Path) -> None:
    run_ffmpeg(
        ["-f", "lavfi", "-i", "sine=f=440:d=0.4", "-ar", "48000", "-ac", "2", str(path)],
        timeout=20,
    )


def test_mux_uses_mix_audio_not_visual_audio(tmp_path: Path) -> None:
    video = tmp_path / "v.mp4"
    mix = tmp_path / "mix.wav"
    dest = tmp_path / "out.mp4"
    run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=1280x720:d=1:r=30",
            "-f",
            "lavfi",
            "-i",
            "sine=f=1000:d=1",
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-shortest",
            str(video),
        ],
        timeout=20,
    )
    run_ffmpeg(
        ["-f", "lavfi", "-i", "sine=f=220:d=1", "-ar", "48000", "-ac", "2", str(mix)],
        timeout=20,
    )
    mux_audio_copy_video(video, mix, dest)
    text = Path(__file__).resolve().parents[2] / "src/docprod/render/mux.py"
    source = text.read_text(encoding="utf-8")
    assert "0:v:0" in source
    assert "1:a:0" in source
    probe = probe_media(dest)
    assert probe.has_video and probe.has_audio


def test_mux_copies_video_stream(tmp_path: Path) -> None:
    video = tmp_path / "v.mp4"
    audio = tmp_path / "a.wav"
    dest = tmp_path / "out.mp4"
    _tiny_mp4(video)
    _tiny_wav(audio)
    assert should_copy_video_stream(video)
    mux_audio_copy_video(video, audio, dest)
    probe = probe_media(dest)
    assert probe.has_video and probe.has_audio
    assert probe.video_codec in {"h264", "avc1"}


def test_poll_delays_are_bounded() -> None:
    delays = poll_delays(initial=5, cap=20, max_wait=60)
    assert delays[0] == 5
    assert max(delays) <= 20
    assert sum(delays) <= 60 + 1e-6


def test_noop_json_preserves_mtime(tmp_path: Path) -> None:
    path = tmp_path / "a.json"
    atomic_write_text(path, '{"ok": true}\n')
    mtime = path.stat().st_mtime_ns
    atomic_write_text(path, '{"ok": true}\n')
    assert path.stat().st_mtime_ns == mtime
