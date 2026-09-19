from __future__ import annotations

from pathlib import Path

from docprod.audio.models import RuntimeSceneTiming, RuntimeTimeline
from docprod.audio.sound_models import SonicProfile, SoundCue, SoundPlan
from docprod.audio.soundtrack_mix import duck_volume_expr, mix_soundtrack
from docprod.providers.pricing import MUSIC_DUCK_DB
from docprod.render.ffmpeg import run_ffmpeg
from docprod.render.mux import mux_audio_copy_video


def _sine(path: Path, freq: int, seconds: float, volume: str = "1.0") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            f"sine=f={freq}:d={seconds}",
            "-af",
            f"volume={volume}",
            "-ar",
            "48000",
            "-ac",
            "2",
            str(path),
        ],
        timeout=20,
    )


def _rms(path: Path, start: float, duration: float = 0.4, *, highpass: int | None = None) -> float:
    import subprocess

    af = "astats=metadata=1:reset=1"
    if highpass:
        af = f"highpass=f={highpass},{af}"
    completed = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-ss",
            str(start),
            "-t",
            str(duration),
            "-i",
            str(path),
            "-af",
            af,
            "-f",
            "null",
            "-",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    for line in reversed(completed.stderr.splitlines()):
        if "RMS level dB" in line:
            return float(line.split(":")[-1].strip())
    raise AssertionError("no RMS")


def test_duck_expr_never_defaults_to_silence_and_is_single_gain() -> None:
    ducked = 10 ** (MUSIC_DUCK_DB / 20)
    open_level = 10 ** ((MUSIC_DUCK_DB + 6) / 20)
    expr = duck_volume_expr([(0.0, 174.2), (212.1, 430.9)], ducked=ducked, open_level=open_level)
    assert "between(t,212.100,430.900)" in expr
    assert not expr.startswith("0.00000")
    assert expr.startswith(f"{open_level:.5f}")


def test_mix_keeps_music_energy_after_intentional_silence(tmp_path: Path) -> None:
    narration = tmp_path / "nar.wav"
    music = tmp_path / "music.wav"
    dest = tmp_path / "mix.wav"
    _sine(narration, 180, 8.0, "0.15")
    _sine(music, 880, 3.0, "0.8")
    plan = SoundPlan(
        project_id="tiny",
        duration=8.0,
        sonic_profile=SonicProfile(),
        cues=[
            SoundCue(
                cue_id="cue_music_04",
                sound_need_id="music_04",
                type="music",
                start=4.0,
                end=8.0,
                asset_id="music_04",
                gain_db=MUSIC_DUCK_DB,
                duck_under_voice=True,
                fade_in=0.05,
                fade_out=0.05,
            )
        ],
    )
    timeline = RuntimeTimeline(
        project_id="tiny",
        audio_duration=8.0,
        total_duration=8.0,
        scenes=[
            RuntimeSceneTiming(
                scene_id="s1",
                start=0.0,
                end=8.0,
                duration=8.0,
                planned_duration=8.0,
                narration="speech throughout",
                asset_unit_id="au",
            )
        ],
    )
    mix_soundtrack(
        narration=narration,
        plan=plan,
        assets={"music_04": music},
        dest=dest,
        timeline=timeline,
    )
    before = _rms(dest, 1.0, highpass=600)
    after = _rms(dest, 5.5, highpass=600)
    assert after > before + 8.0


def test_mux_ignores_visual_source_audio(tmp_path: Path) -> None:
    video = tmp_path / "visual.mp4"
    mix = tmp_path / "mix.wav"
    out = tmp_path / "prod.mp4"
    run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=1280x720:d=1.2:r=30",
            "-f",
            "lavfi",
            "-i",
            "sine=f=1200:d=1.2",
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
    _sine(mix, 220, 1.2, "0.5")
    mux_audio_copy_video(video, mix, out)
    assert _rms(out, 0.3, highpass=900) < _rms(video, 0.3, highpass=900) - 8
