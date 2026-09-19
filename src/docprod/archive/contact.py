from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from docprod.archive.models import ArchiveCandidate
from docprod.graphics.fonts import discover_sans_font, load_font

THUMB_W = 320
THUMB_H = 180
LABEL_H = 90
COLUMNS = 4
MAX_TILES = 16


def build_archive_contact_sheet(
    candidates: list[ArchiveCandidate],
    dest: Path,
    *,
    fetch_bytes,
) -> Path | None:
    ranked = sorted(candidates, key=lambda item: item.score, reverse=True)[:MAX_TILES]
    if not ranked:
        return None
    font = load_font(discover_sans_font(), 12)
    cols = min(COLUMNS, len(ranked))
    rows = (len(ranked) + cols - 1) // cols
    cell_h = THUMB_H + LABEL_H
    sheet = Image.new("RGB", (cols * THUMB_W, rows * cell_h), (10, 10, 12))
    draw = ImageDraw.Draw(sheet)
    for index, candidate in enumerate(ranked):
        col = index % cols
        row = index // cols
        x = col * THUMB_W
        y = row * cell_h
        thumb = Image.new("RGB", (THUMB_W, THUMB_H), (30, 34, 40))
        url = candidate.thumb_url or candidate.file_url
        if url:
            try:
                image = Image.open(BytesIO(fetch_bytes(url))).convert("RGB")
                image.thumbnail((THUMB_W, THUMB_H))
                thumb.paste(
                    image,
                    ((THUMB_W - image.width) // 2, (THUMB_H - image.height) // 2),
                )
            except Exception:  # noqa: BLE001
                pass
        sheet.paste(thumb, (x, y))
        caption = (
            f"#{index + 1} {candidate.title[:40]}\n"
            f"{candidate.date_original[:10]} {candidate.artist[:24]}\n"
            f"{candidate.license_short_name} {candidate.width}x{candidate.height}\n"
            f"{candidate.decision}"
        )
        draw.multiline_text(
            (x + 6, y + THUMB_H + 4),
            caption,
            font=font if isinstance(font, ImageFont.FreeTypeFont) else None,
            fill=(230, 230, 230),
            spacing=1,
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(dest, "JPEG", quality=85)
    return dest
