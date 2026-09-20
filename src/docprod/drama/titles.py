from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from docprod.graphics import GRAPHIC_HEIGHT, GRAPHIC_WIDTH
from docprod.graphics.fonts import discover_sans_font


def render_cinematic_title_card(title: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (GRAPHIC_WIDTH, GRAPHIC_HEIGHT), (6, 6, 8))
    draw = ImageDraw.Draw(image)
    font_path = discover_sans_font()
    size = 64
    font = ImageFont.truetype(str(font_path), size=size)
    while size > 28:
        font = ImageFont.truetype(str(font_path), size=size)
        box = draw.textbbox((0, 0), title, font=font)
        if box[2] - box[0] < GRAPHIC_WIDTH - 180:
            break
        size -= 4
    box = draw.textbbox((0, 0), title, font=font)
    width = box[2] - box[0]
    height = box[3] - box[1]
    x = (GRAPHIC_WIDTH - width) / 2
    y = (GRAPHIC_HEIGHT - height) / 2 - 8
    draw.rectangle(
        [(GRAPHIC_WIDTH * 0.22, y + height + 18), (GRAPHIC_WIDTH * 0.78, y + height + 20)],
        fill=(180, 170, 150),
    )
    draw.text((x, y), title, font=font, fill=(236, 230, 220))
    image.save(dest, format="JPEG", quality=92)
    return dest
