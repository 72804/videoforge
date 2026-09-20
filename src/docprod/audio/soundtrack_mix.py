from __future__ import annotations

from pathlib import Path

from docprod.audio.models import RuntimeTimeline
from docprod.audio.sound_models import SoundPlan
from docprod.providers.pricing import MUSIC_GAP_LIFT_DB, TARGET_LUFS, TRUE_PEAK_DBTP
from docprod.render.ffmpeg import run_ffmpeg


def synthesize_generic(kind: str, dest: Path, duration: float = 2.0) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp.wav")
    if kind in {"ambience", "apartment", "stairwell", "bakkal"}:
        src = f"anoisesrc=d={duration}:c=brown:r=48000:a=0.06"
        filt = "lowpass=f=320,highpass=f=35,volume=-24dB"
    elif kind == "elevator":
        src = f"sine=f=88:d={duration}"
        filt = (
            "aformat=sample_fmts=s16:sample_rates=48000:channel_layouts=stereo,"
            "volume=-28dB,lowpass=f=220"
        )
    elif kind == "metal":
        src = f"sine=f=180:d={min(duration, 0.35)}"
        filt = "aformat=sample_fmts=s16:sample_rates=48000:channel_layouts=stereo,volume=-18dB"
    elif kind in {"sting", "chapter_sting"}:
        src = f"anoisesrc=d={min(duration, 0.32)}:c=white:r=48000:a=0.12"
        filt = (
            "highpass=f=280,lowpass=f=3500,afade=t=in:st=0:d=0.02,"
            "afade=t=out:st=0.12:d=0.18,volume=-16dB"
        )
    elif kind == "ledger":
        src = f"sine=f=72:d={min(duration, 0.22)}"
        filt = (
            "aformat=sample_fmts=s16:sample_rates=48000:channel_layouts=stereo,"
            "afade=t=out:st=0.08:d=0.12,volume=-12dB"
        )
    elif kind == "pocket":
        src = f"anoisesrc=d={min(duration, 0.45)}:c=white:r=48000:a=0.05"
        filt = "bandpass=f=420:w=280,afade=t=out:st=0.2:d=0.22,volume=-26dB"
    elif kind == "cola":
        src = f"sine=f=920:d={min(duration, 0.08)}"
        filt = (
            "aformat=sample_fmts=s16:sample_rates=48000:channel_layouts=stereo,"
            "afade=t=out:st=0.03:d=0.05,volume=-18dB"
        )
    elif kind == "window":
        src = f"anoisesrc=d={min(duration, 0.35)}:c=white:r=48000:a=0.05"
        filt = "bandpass=f=900:w=600,afade=t=out:st=0.12:d=0.2,volume=-22dB"
    else:
        src = f"anoisesrc=d={min(duration, 1.2)}:c=white:r=48000:a=0.04"
        filt = "bandpass=f=1800:w=800,volume=-24dB"
    try:
        run_ffmpeg(
            [
                "-f",
                "lavfi",
                "-i",
                src,
                "-af",
                filt,
                "-ar",
                "48000",
                "-ac",
                "2",
                "-c:a",
                "pcm_s16le",
                str(tmp),
            ],
            timeout=60,
        )
        tmp.replace(dest)
    finally:
        tmp.unlink(missing_ok=True)


def mix_soundtrack(
    *,
    narration: Path,
    plan: SoundPlan,
    assets: dict[str, Path],
    dest: Path,
    timeline: RuntimeTimeline,
    loop_music: bool = True,
) -> dict[str, str]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    inputs = ["-i", str(narration)]
    filters: list[str] = []
    mix_labels = ["[0:a]"]
    index = 1
    speech_windows = [(item.start, item.end) for item in timeline.scenes if item.narration.strip()]
    for cue in plan.cues:
        if cue.type == "silence":
            continue
        source = assets.get(cue.asset_id) or assets.get(cue.sound_need_id)
        if source is None or not source.is_file():
            continue
        if cue.type == "music" and loop_music:
            inputs.extend(["-stream_loop", "-1", "-i", str(source)])
        else:
            inputs.extend(["-i", str(source)])
        duration = max(0.05, cue.end - cue.start)
        delay_ms = int(round(cue.start * 1000))
        ducked = 10 ** (cue.gain_db / 20)
        if cue.duck_under_voice and cue.type == "music":
            open_level = 10 ** ((cue.gain_db + MUSIC_GAP_LIFT_DB) / 20)
            vol_expr = duck_volume_expr(speech_windows, ducked=ducked, open_level=open_level)
            volume = f"volume='{vol_expr}':eval=frame"
        else:
            volume = f"volume={ducked:.5f}"
        fade = (
            f"afade=t=in:st=0:d={cue.fade_in},afade=t=out:st={max(0.0, duration - cue.fade_out)}:"
            f"d={cue.fade_out}"
        )
        filters.append(
            f"[{index}:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
            f"atrim=0:{duration:.4f},{fade},adelay={delay_ms}|{delay_ms},{volume}[a{index}]"
        )
        mix_labels.append(f"[a{index}]")
        index += 1
    n = len(mix_labels)
    filters.append(
        f"{''.join(mix_labels)}amix=inputs={n}:duration=longest:dropout_transition=2:normalize=0[mix]"
    )
    tmp = dest.with_suffix(".tmp.wav")
    try:
        run_ffmpeg(
            [
                *inputs,
                "-filter_complex",
                ";".join(filters),
                "-map",
                "[mix]",
                "-ar",
                "48000",
                "-ac",
                "2",
                "-c:a",
                "pcm_s16le",
                str(tmp),
            ],
            timeout=300,
        )
        loud = f"loudnorm=I={TARGET_LUFS}:TP={TRUE_PEAK_DBTP}:LRA=11"
        run_ffmpeg(
            [
                "-i",
                str(tmp),
                "-af",
                loud,
                "-ar",
                "48000",
                "-ac",
                "2",
                "-c:a",
                "pcm_s16le",
                str(dest),
            ],
            timeout=300,
        )
    finally:
        tmp.unlink(missing_ok=True)
    from docprod.audio.mix import measure_loudnorm

    return measure_loudnorm(dest)


def duck_volume_expr(
    windows: list[tuple[float, float]], *, ducked: float, open_level: float
) -> str:
    """Under speech use `ducked`; otherwise `open_level`. Never default to 0."""
    if not windows:
        return f"{open_level:.5f}"
    speech = "+".join(f"between(t,{start:.3f},{end:.3f})" for start, end in windows)
    delta = ducked - open_level
    return f"{open_level:.5f}+min(1,{speech})*{delta:.5f}"
