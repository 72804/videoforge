from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from docprod.graphics.fonts import discover_sans_font, load_font
from docprod.stock.base import StockVideoProvider
from docprod.stock.models import StockVideoCandidate

THUMB_W = 320
THUMB_H = 180
LABEL_H = 78
MAX_TILES = 24
COLUMNS = 4


def _placeholder_thumb() -> Image.Image:
    image = Image.new("RGB", (THUMB_W, THUMB_H), (28, 32, 40))
    draw = ImageDraw.Draw(image)
    draw.text((12, 72), "no preview", fill=(180, 180, 180))
    return image


def _load_thumb(payload: bytes) -> Image.Image:
    try:
        image = Image.open(BytesIO(payload)).convert("RGB")
    except OSError:
        return _placeholder_thumb()
    image.thumbnail((THUMB_W, THUMB_H))
    canvas = Image.new("RGB", (THUMB_W, THUMB_H), (0, 0, 0))
    x = (THUMB_W - image.width) // 2
    y = (THUMB_H - image.height) // 2
    canvas.paste(image, (x, y))
    return canvas


def build_candidate_contact_sheet(
    candidates: list[StockVideoCandidate],
    dest: Path,
    *,
    provider: StockVideoProvider,
) -> Path | None:
    ranked = sorted(candidates, key=lambda item: item.score, reverse=True)[:MAX_TILES]
    if not ranked:
        return None
    font = load_font(discover_sans_font(), 14)
    small = load_font(discover_sans_font(), 12)
    cols = min(COLUMNS, len(ranked))
    rows = (len(ranked) + cols - 1) // cols
    cell_h = THUMB_H + LABEL_H
    sheet = Image.new("RGB", (cols * THUMB_W, rows * cell_h), (8, 8, 10))
    draw = ImageDraw.Draw(sheet)
    for index, candidate in enumerate(ranked):
        col = index % cols
        row = index // cols
        x = col * THUMB_W
        y = row * cell_h
        thumb = _placeholder_thumb()
        if candidate.preview_image_url:
            try:
                thumb = _load_thumb(provider.fetch_bytes(candidate.preview_image_url))
            except Exception:  # noqa: BLE001 — preview fetch is best-effort
                thumb = _placeholder_thumb()
        sheet.paste(thumb, (x, y))
        caption = (
            f"#{index + 1} id={candidate.provider_video_id}\n"
            f"{candidate.duration:.0f}s {candidate.width}x{candidate.height}\n"
            f"{candidate.query}\n"
            f"{candidate.creator_name}"
        )
        draw.multiline_text(
            (x + 6, y + THUMB_H + 4),
            caption[:180],
            font=small if isinstance(small, ImageFont.FreeTypeFont) else font,
            fill=(230, 230, 230),
            spacing=2,
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    sheet.convert("RGB").save(dest, "JPEG", quality=85)
    return dest
