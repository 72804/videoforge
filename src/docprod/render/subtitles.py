from __future__ import annotations

from pathlib import Path

from docprod.models.scene import Scene, ScenePlan
from docprod.storage.json_store import atomic_write_text


def srt_timestamp(seconds: float) -> str:
    total_ms = max(0, int(round(seconds * 1000)))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def ass_timestamp(seconds: float) -> str:
    total_cs = max(0, int(round(seconds * 100)))
    hours, rem = divmod(total_cs, 360_000)
    minutes, rem = divmod(rem, 6_000)
    secs, cs = divmod(rem, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{cs:02d}"


def wrap_caption(text: str, *, width: int = 42, max_lines: int = 2) -> list[str]:
    compact = " ".join(text.split())
    if not compact:
        return []
    words = compact.split(" ")
    lines: list[str] = [""]
    for word in words:
        candidate = word if not lines[-1] else f"{lines[-1]} {word}"
        if len(candidate) <= width:
            lines[-1] = candidate
            continue
        if len(lines) >= max_lines:
            leftover = compact[len(" ".join(lines)) :].strip()
            if leftover:
                lines[-1] = (lines[-1] + " " + leftover).strip()
            break
        lines.append(word)
    if len(lines) > max_lines:
        lines = lines[: max_lines - 1] + [" ".join(lines[max_lines - 1 :])]
    # Hard-cap last line length for layout.
    fitted: list[str] = []
    for index, line in enumerate(lines[:max_lines]):
        if len(line) <= width + 8 or index < max_lines - 1:
            fitted.append(line)
        else:
            fitted.append(line[: width + 8].rstrip())
    return [line for line in fitted if line]


def _ass_escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}")


def build_srt(plan: ScenePlan) -> str:
    cues: list[str] = []
    index = 1
    for scene in plan.scenes:
        if not scene.subtitle.strip():
            continue
        lines = wrap_caption(scene.subtitle)
        if not lines:
            continue
        cues.append(
            f"{index}\n{srt_timestamp(scene.start)} --> {srt_timestamp(scene.end)}\n"
            + "\n".join(lines)
        )
        index += 1
    return "\n\n".join(cues) + ("\n" if cues else "")


def build_ass(
    plan: ScenePlan,
    *,
    play_res_x: int,
    play_res_y: int,
    font_name: str = "Arial",
) -> str:
    fontsize = max(18, play_res_y // 20)
    margin_v = max(28, play_res_y // 13)
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {play_res_x}\n"
        f"PlayResY: {play_res_y}\n"
        "WrapStyle: 0\n"
        "ScaledBorderAndShadow: yes\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{font_name},{fontsize},&H00FFFFFF,&H000000FF,&H00000000,&H64000000,"
        f"0,0,0,0,100,100,0,0,1,2.4,0.8,2,70,70,{margin_v},1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    events: list[str] = []
    for scene in plan.scenes:
        if not scene.subtitle.strip():
            continue
        lines = wrap_caption(scene.subtitle)
        if not lines:
            continue
        text = r"\N".join(_ass_escape(line) for line in lines)
        events.append(
            f"Dialogue: 0,{ass_timestamp(scene.start)},{ass_timestamp(scene.end)},"
            f"Default,,0,0,0,,{text}"
        )
    return header + "\n".join(events) + ("\n" if events else "")


def write_captions(
    plan: ScenePlan,
    *,
    srt_path: Path,
    ass_path: Path,
    play_res_x: int,
    play_res_y: int,
    font_name: str = "Arial",
) -> None:
    atomic_write_text(srt_path, build_srt(plan))
    atomic_write_text(
        ass_path,
        build_ass(plan, play_res_x=play_res_x, play_res_y=play_res_y, font_name=font_name),
    )


def scene_has_caption(scene: Scene) -> bool:
    return bool(scene.subtitle.strip())
