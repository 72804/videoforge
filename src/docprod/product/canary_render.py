from __future__ import annotations

from pathlib import Path

from docprod.audio.cues import chunk_alignment_cues
from docprod.audio.models import AlignedToken, AlignmentReport
from docprod.render.ffmpeg import run_ffmpeg
from docprod.render.subtitles import build_ass_from_cues, build_srt_from_cues
from docprod.storage.json_store import atomic_write_text


def even_split_alignment(text: str, duration: float) -> AlignmentReport:
    words = [token for token in text.replace("\n", " ").split() if token]
    if not words:
        words = ["..."]
    span = duration / len(words)
    tokens: list[AlignedToken] = []
    cursor = 0.0
    for word in words:
        end = min(duration, cursor + span)
        tokens.append(
            AlignedToken(
                text=word,
                scene_id="canary",
                start=cursor,
                end=end,
                status="interpolated",
                interpolated=True,
                timing_source="even_split",
            )
        )
        cursor = end
    count = len(tokens)
    return AlignmentReport(
        project_id="videoforge_local_canary",
        canonical_word_count=count,
        matched_word_count=0,
        interpolated_word_count=count,
        unmatched_word_count=0,
        match_fraction=0.0,
        tokens=tokens,
        quality_passed=False,
    )


def render_canary_preview(
    *,
    segments: list[tuple[str, Path, float]],
    tts_wav: Path | None,
    narration: str,
    dest: Path,
    work: Path,
) -> Path:
    """Compose stills/clips + TTS with local FFmpeg. Deterministic subtitle fallback."""
    work.mkdir(parents=True, exist_ok=True)
    dest.parent.mkdir(parents=True, exist_ok=True)
    pieces: list[Path] = []
    for index, (kind, source, duration) in enumerate(segments):
        out = work / f"seg_{index:02d}.mp4"
        if kind == "video":
            run_ffmpeg(
                [
                    "-y",
                    "-i",
                    str(source),
                    "-t",
                    f"{duration:.3f}",
                    "-vf",
                    "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920",
                    "-an",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    str(out),
                ],
                timeout=180,
            )
        else:
            run_ffmpeg(
                [
                    "-y",
                    "-loop",
                    "1",
                    "-i",
                    str(source),
                    "-t",
                    f"{duration:.3f}",
                    "-vf",
                    "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
                    "zoompan=z='min(zoom+0.0008,1.08)':d=1:s=1080x1920:fps=24",
                    "-an",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    str(out),
                ],
                timeout=180,
            )
        pieces.append(out)
    concat_list = work / "concat.txt"
    concat_list.write_text(
        "".join(f"file '{path}'\n" for path in pieces), encoding="utf-8"
    )
    silent = work / "picture.mp4"
    run_ffmpeg(
        [
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list),
            "-c",
            "copy",
            str(silent),
        ],
        timeout=120,
    )
    total = sum(item[2] for item in segments)
    report = even_split_alignment(narration, total)
    cues = chunk_alignment_cues(report)
    atomic_write_text(work / "canary.srt", build_srt_from_cues(cues))
    atomic_write_text(
        work / "canary.ass",
        build_ass_from_cues(cues, play_res_x=1080, play_res_y=1920),
    )
    cmd = ["-y", "-i", str(silent)]
    if tts_wav is not None and tts_wav.is_file():
        cmd.extend(["-i", str(tts_wav)])
        cmd.extend(["-shortest", "-c:v", "copy", "-c:a", "aac"])
    else:
        cmd.extend(["-c:v", "copy"])
    cmd.append(str(dest))
    run_ffmpeg(cmd, timeout=180)
    return dest
