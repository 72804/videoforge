from __future__ import annotations

from pathlib import Path

from docprod.render.ffmpeg import discover_font, escape_drawtext, escape_filter_path, run_ffmpeg
from docprod.render.still import resolve_generated_still
from docprod.storage.paths import ProjectPaths

THUMB_W = 320
THUMB_H = 180
LABEL_H = 36


def build_contact_sheet(
    paths: ProjectPaths,
    entries: list[tuple[str, str, Path]],
    *,
    columns: int = 4,
    output: Path | None = None,
) -> Path | None:
    """Local FFmpeg contact sheet. entries = (scene_id, strategy, image_path)."""
    usable = [(scene_id, strategy, path) for scene_id, strategy, path in entries if path.is_file()]
    if not usable:
        return None
    font = discover_font()
    cols = max(1, min(columns, len(usable)))
    rows = (len(usable) + cols - 1) // cols
    cell_h = THUMB_H + LABEL_H
    filters: list[str] = []
    labels: list[str] = []
    inputs: list[str] = []
    for index, (scene_id, strategy, image_path) in enumerate(usable):
        inputs.extend(["-i", str(image_path)])
        text = escape_drawtext(f"{scene_id} {strategy}")
        filters.append(
            f"[{index}:v]scale={THUMB_W}:{THUMB_H}:force_original_aspect_ratio=decrease:"
            f"flags=lanczos,pad={THUMB_W}:{THUMB_H}:(ow-iw)/2:(oh-ih)/2:black,"
            f"pad={THUMB_W}:{cell_h}:0:0:black,"
            f"drawtext=fontfile={escape_filter_path(font)}:text='{text}':"
            f"x=8:y={THUMB_H + 8}:fontsize=16:fontcolor=white:borderw=1[v{index}]"
        )
        labels.append(f"[v{index}]")
    while len(labels) < cols * rows:
        pad_index = len(labels)
        filters.append(
            f"color=c=black:s={THUMB_W}x{cell_h}:d=1,format=yuv420p[v{pad_index}]"
        )
        labels.append(f"[v{pad_index}]")
        # color source doesn't need an extra -i when using lavfi in filtergraph
    layout_parts: list[str] = []
    for index in range(cols * rows):
        x = (index % cols) * THUMB_W
        y = (index // cols) * cell_h
        layout_parts.append(f"{x}_{y}")
    stacked = "".join(labels[: cols * rows])
    filters.append(
        f"{stacked}xstack=inputs={cols * rows}:layout={'|'.join(layout_parts)}:"
        f"fill=black,format=yuv420p[out]"
    )
    dest = output or paths.contact_sheet()
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Pad cells that have no corresponding input use color filter; they must not
    # consume file inputs. Rebuild so only real images are -i.
    args = [*inputs, "-filter_complex", ";".join(filters), "-map", "[out]", "-frames:v", "1"]
    run_ffmpeg([*args, str(dest)], timeout=120)
    return dest


def contact_sheet_from_plan(
    paths: ProjectPaths,
    scene_ids: list[tuple[str, str]],
    *,
    output: Path | None = None,
    columns: int = 4,
) -> Path | None:
    entries: list[tuple[str, str, Path]] = []
    for scene_id, strategy in scene_ids:
        resolved = resolve_generated_still(paths, scene_id)
        if resolved is None:
            continue
        entries.append((scene_id, strategy, resolved[0]))
    return build_contact_sheet(paths, entries, output=output, columns=columns)


def build_repair_contact_sheet(
    paths: ProjectPaths,
    pairs: list[tuple[str, Path, Path]],
) -> Path | None:
    """Two-column OLD | NEW comparison for targeted still repairs."""
    entries: list[tuple[str, str, Path]] = []
    for scene_id, old_path, new_path in pairs:
        entries.append((scene_id, "OLD", old_path))
        entries.append((scene_id, "NEW", new_path))
    return build_contact_sheet(
        paths,
        entries,
        columns=2,
        output=paths.contact_sheet_repairs(),
    )
