from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from docprod.product.episode import AnimaticPlan, AnimaticShotEdit, AnimaticVoiceLine
from docprod.product.errors import ProductError
from docprod.render.ffmpeg import (
    discover_font,
    escape_drawtext,
    probe_media,
    run_ffmpeg,
)
from docprod.render.subtitles import ass_timestamp, ffmpeg_subtitle_filter, wrap_caption
from docprod.storage.json_store import atomic_write_text

FPS = 24


@dataclass(frozen=True)
class DialogueCue:
    speaker: str
    source: Path
    start: float
    duration: float
    end: float
    text: str
    shot_id: str
    line_id: str


@dataclass(frozen=True)
class VisualCue:
    shot_id: str
    source: Path
    start: float
    duration: float
    end: float
    motion: str
    overlay_kind: str
    overlay_copy: tuple[str, ...]


def voice_path_for(line: AnimaticVoiceLine, voice_dir: Path) -> Path:
    return voice_dir / f"{line.line_id}.wav"


def still_path_for(shot: AnimaticShotEdit, still_dir: Path) -> Path:
    return still_dir / f"{shot.keyframe_id}.jpg"


def actual_audio_duration(path: Path) -> float:
    info = probe_media(path)
    return max(0.05, float(info.duration or 0.0))


def build_visual_and_dialogue_timelines(
    plan: AnimaticPlan,
    *,
    still_dir: Path,
    voice_dir: Path,
) -> tuple[list[VisualCue], list[DialogueCue], float]:
    missing_stills: list[str] = []
    missing_voices: list[str] = []
    by_shot: dict[str, list[tuple[AnimaticVoiceLine, Path, float]]] = {}
    for line in plan.voice_lines:
        path = voice_path_for(line, voice_dir)
        if not path.is_file():
            missing_voices.append(line.line_id)
            continue
        by_shot.setdefault(line.shot_id, []).append((line, path, actual_audio_duration(path)))
    if missing_voices:
        raise ProductError(f"missing paid voice clips: {missing_voices}")

    visuals: list[VisualCue] = []
    dialogue: list[DialogueCue] = []
    cursor = 0.0
    for shot in plan.shots:
        still = still_path_for(shot, still_dir)
        if not still.is_file():
            missing_stills.append(shot.keyframe_id)
            continue
        clips = by_shot.get(shot.shot_id, [])
        speech = sum(item[2] for item in clips)
        duration = max(float(shot.edit_duration_seconds), speech, 1.0)
        start = cursor
        end = start + duration
        visuals.append(
            VisualCue(
                shot_id=shot.shot_id,
                source=still,
                start=start,
                duration=duration,
                end=end,
                motion=shot.motion,
                overlay_kind=shot.overlay_kind,
                overlay_copy=tuple(shot.overlay_copy),
            )
        )
        offset = start
        for line, path, clip_dur in clips:
            cue_end = offset + clip_dur
            dialogue.append(
                DialogueCue(
                    speaker=line.speaker,
                    source=path,
                    start=offset,
                    duration=clip_dur,
                    end=cue_end,
                    text=line.text,
                    shot_id=shot.shot_id,
                    line_id=line.line_id,
                )
            )
            offset = cue_end
        cursor = end
    if missing_stills:
        raise ProductError(f"missing paid stills: {sorted(set(missing_stills))}")
    visual_end = visuals[-1].end if visuals else 0.0
    audio_end = max((item.end for item in dialogue), default=0.0)
    total = max(visual_end, audio_end, 1.0)
    return visuals, dialogue, round(total, 3)


def mix_master_dialogue(
    cues: list[DialogueCue],
    *,
    total: float,
    dest: Path,
) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not cues:
        run_ffmpeg(
            [
                "-f",
                "lavfi",
                "-t",
                f"{total:.3f}",
                "-i",
                "anullsrc=r=48000:cl=stereo",
                str(dest),
            ],
            timeout=60,
        )
        return dest
    cmd: list[str] = [
        "-f",
        "lavfi",
        "-t",
        f"{total:.3f}",
        "-i",
        "anullsrc=r=48000:cl=stereo",
    ]
    filters: list[str] = []
    mix_labels = ["[0:a]"]
    for index, cue in enumerate(cues, start=1):
        cmd.extend(["-i", str(cue.source)])
        delay_ms = int(round(cue.start * 1000))
        filters.append(
            f"[{index}:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
            f"adelay={delay_ms}|{delay_ms}[a{index}]"
        )
        mix_labels.append(f"[a{index}]")
    n = len(mix_labels)
    filters.append(
        f"{''.join(mix_labels)}amix=inputs={n}:duration=first:dropout_transition=0:"
        f"normalize=0[mix]"
    )
    cmd.extend(["-filter_complex", ";".join(filters), "-map", "[mix]", str(dest)])
    if "-shortest" in cmd:
        raise ProductError("master dialogue mix must not use -shortest")
    run_ffmpeg(cmd, timeout=180)
    return dest


def _motion_filter(motion: str, duration: float) -> str:
    frames = max(int(round(duration * FPS)), 24)
    base = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"
    if motion == "slow_pull_out":
        zoom = (
            f"zoompan=z='if(eq(on,1),1.08,max(zoom-0.0012,1.0))'"
            f":d={frames}:s=1080x1920:fps={FPS}"
        )
    elif motion in {"pan_left", "pan_right"}:
        zoom = (
            f"zoompan=z=1.08:x='if(eq(on,1),0,x+0.4)':y='ih/2-(ih/zoom/2)':"
            f"d={frames}:s=1080x1920:fps={FPS}"
        )
    else:
        zoom = f"zoompan=z='min(zoom+0.0012,1.08)':d={frames}:s=1080x1920:fps={FPS}"
    return f"{base},{zoom}"


def encode_still_segment(cue: VisualCue, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    vf = _motion_filter(cue.motion, cue.duration)
    if cue.overlay_kind == "phone_ui" and cue.overlay_copy:
        text = escape_drawtext(" / ".join(cue.overlay_copy[:4])[:180])
        font = discover_font().as_posix().replace(":", "\\:")
        vf += (
            f",drawtext=fontfile='{font}':text='{text}':fontsize=28:fontcolor=white:"
            f"x=(w-text_w)/2:y=h*0.08:box=1:boxcolor=black@0.65:boxborderw=12"
        )
    cmd = [
        "-loop",
        "1",
        "-i",
        str(cue.source),
        "-t",
        f"{cue.duration:.3f}",
        "-vf",
        vf,
        "-r",
        str(FPS),
        "-an",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        str(dest),
    ]
    if "-shortest" in cmd:
        raise ProductError("still encode must not use -shortest")
    run_ffmpeg(cmd, timeout=180)
    return dest


def concat_segments(paths: list[Path], dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    manifest = dest.with_suffix(".txt")
    lines: list[str] = []
    for path in paths:
        info = probe_media(path)
        lines.append(f"file '{path}'")
        lines.append(f"duration {info.duration:.4f}")
    atomic_write_text(manifest, "\n".join(lines) + "\n")
    cmd = [
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(manifest),
        "-c",
        "copy",
        str(dest),
    ]
    if "-shortest" in cmd:
        raise ProductError("concat must not use -shortest")
    run_ffmpeg(cmd, timeout=180)
    return dest


def write_timed_subtitles(cues: list[DialogueCue], dest: Path) -> Path:
    events = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1080",
        "PlayResY: 1920",
        "",
        "[V4+ Styles]",
        "Style: Default,Arial,42,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,"
        "0,0,0,0,100,100,0,0,1,2,1,2,80,80,160,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for cue in cues:
        body = r"\N".join(wrap_caption(cue.text))
        events.append(
            f"Dialogue: 0,{ass_timestamp(cue.start)},{ass_timestamp(cue.end)},"
            f"Default,,0,0,0,,{body}"
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(events) + "\n", encoding="utf-8")
    return dest


def mux_animatic_args(
    *,
    video: Path,
    audio: Path,
    duration: float,
    dest: Path,
) -> list[str]:
    return [
        "-i",
        str(video),
        "-i",
        str(audio),
        "-t",
        f"{duration:.3f}",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        str(dest),
    ]


def mux_animatic(
    *,
    video: Path,
    audio: Path,
    subtitles: Path,
    dest: Path,
    duration: float,
) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    staged = dest.with_name(dest.stem + "_mux.mp4")
    cmd = mux_animatic_args(video=video, audio=audio, duration=duration, dest=staged)
    if "-shortest" in cmd:
        raise ProductError("animatic mux must not use -shortest")
    run_ffmpeg(cmd, timeout=180)
    burn = [
        "-i",
        str(staged),
        "-vf",
        ffmpeg_subtitle_filter(subtitles),
        "-t",
        f"{duration:.3f}",
        "-c:a",
        "copy",
        str(dest),
    ]
    if "-shortest" in burn:
        raise ProductError("subtitle burn-in must not use -shortest")
    run_ffmpeg(burn, timeout=180)
    return dest


def _reuse_legacy_segment(legacy: Path, needed: float, dest: Path) -> bool:
    if not legacy.is_file():
        return False
    info = probe_media(legacy)
    if abs(info.duration - needed) > 0.08:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(legacy, dest)
    return True


def render_existing_animatic(
    plan: AnimaticPlan,
    *,
    work_dir: Path,
    dest: Path,
) -> dict[str, object]:
    still_dir = work_dir / "stills"
    voice_dir = work_dir / "voices"
    rebuild = work_dir / "ffmpeg_repair"
    rebuild.mkdir(parents=True, exist_ok=True)
    visuals, dialogue, total = build_visual_and_dialogue_timelines(
        plan, still_dir=still_dir, voice_dir=voice_dir
    )
    timeline_path = rebuild / "timeline.json"
    atomic_write_text(
        timeline_path,
        json.dumps(
            {
                "total": total,
                "visuals": [
                    {
                        "shot_id": item.shot_id,
                        "source": str(item.source),
                        "start": item.start,
                        "duration": item.duration,
                        "end": item.end,
                        "motion": item.motion,
                    }
                    for item in visuals
                ],
                "dialogue": [
                    {
                        "speaker": item.speaker,
                        "source": str(item.source),
                        "start": item.start,
                        "duration": item.duration,
                        "end": item.end,
                        "text": item.text,
                        "shot_id": item.shot_id,
                        "line_id": item.line_id,
                    }
                    for item in dialogue
                ],
            },
            indent=2,
        )
        + "\n",
    )
    segments: list[Path] = []
    legacy_dir = work_dir / "ffmpeg"
    for index, cue in enumerate(visuals):
        dest_seg = rebuild / f"shot_{index:02d}.mp4"
        legacy = legacy_dir / f"seg_{index:02d}.mp4"
        if not _reuse_legacy_segment(legacy, cue.duration, dest_seg):
            encode_still_segment(cue, dest_seg)
        segments.append(dest_seg)
    picture = concat_segments(segments, rebuild / "picture.mp4")
    master = mix_master_dialogue(dialogue, total=total, dest=rebuild / "dialogue_master.wav")
    ass_path = write_timed_subtitles(dialogue, work_dir / "animatic.ass")
    mux_animatic(video=picture, audio=master, subtitles=ass_path, dest=dest, duration=total)
    probed = probe_media(dest)
    if probed.duration + 0.5 < total:
        raise ProductError(
            f"repaired animatic duration {probed.duration:.3f}s "
            f"is shorter than timeline {total:.3f}s"
        )
    return {
        "output": str(dest),
        "duration": probed.duration,
        "width": probed.width,
        "height": probed.height,
        "video_codec": probed.video_codec,
        "audio_codec": probed.audio_codec,
        "visual_end": visuals[-1].end if visuals else 0.0,
        "audio_end": max((item.end for item in dialogue), default=0.0),
        "subtitle_end": max((item.end for item in dialogue), default=0.0),
        "shot_count": len(visuals),
        "dialogue_cues": len(dialogue),
        "stills_reused": len({item.source for item in visuals}),
        "voices_reused": len({item.source for item in dialogue}),
        "timeline": str(timeline_path),
        "provider_http_calls": 0,
    }
