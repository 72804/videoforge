from __future__ import annotations

from PIL import Image, ImageDraw

from docprod.graphics import GRAPHIC_HEIGHT, GRAPHIC_WIDTH
from docprod.graphics.document import blend_grain, desk_background, paste_shadow, wrap_text
from docprod.graphics.fonts import discover_sans_font, discover_serif_font, load_font
from docprod.models.scene import Scene


def _headline(scene: Scene) -> str:
    text = scene.narration.strip().rstrip(".")
    if len(text) > 64:
        text = text[:61].rsplit(" ", 1)[0] + "…"
    return text.upper()


def render_newspaper_graphic(scene: Scene, *, seed: str) -> tuple[Image.Image, dict[str, str], str]:
    serif = load_font(discover_serif_font(), 42)
    serif_small = load_font(discover_serif_font(), 18)
    sans = load_font(discover_sans_font(), 16)
    masthead_font = load_font(discover_serif_font(), 48)
    canvas = desk_background((GRAPHIC_WIDTH, GRAPHIC_HEIGHT), f"{seed}:news")
    clip = Image.new("RGB", (1040, 700), (236, 230, 214))
    draw = ImageDraw.Draw(clip)
    fields = {
        "masthead": "GÜNLÜK KAYIT",
        "kicker": "yerel bülten",
        "headline": _headline(scene),
        "fact": scene.narration.strip(),
        "date": "arşiv kupürü",
    }
    draw.rectangle((0, 0, 1039, 699), outline=(90, 84, 70))
    draw.text((36, 22), fields["masthead"], font=masthead_font, fill=(28, 24, 20))
    draw.text((820, 40), fields["kicker"], font=sans, fill=(90, 82, 70))
    draw.line((36, 84, 1004, 84), fill=(30, 26, 22), width=3)
    draw.line((36, 92, 1004, 92), fill=(30, 26, 22), width=1)
    y = 110
    for line in wrap_text(fields["headline"], serif, 980)[:3]:
        draw.text((36, y), line, font=serif, fill=(20, 18, 16))
        y += 50
    draw.line((36, y + 4, 1004, y + 4), fill=(60, 54, 44), width=1)
    draw.rectangle((36, y + 24, 360, y + 250), fill=(70, 68, 64), outline=(40, 38, 36))
    draw.text((48, y + 230), "fotoğraf alanı", font=sans, fill=(200, 196, 186))
    body = wrap_text(fields["fact"], serif_small, 600)[:6]
    by = y + 28
    for line in body:
        draw.text((384, by), line, font=serif_small, fill=(32, 28, 24))
        by += 24
    for index in range(8):
        yy = by + 10 + index * 14
        draw.rectangle((384, yy, 980, yy + 6), fill=(210, 204, 190))
    draw.text((36, 660), fields["date"], font=sans, fill=(90, 82, 70))
    draw.text((700, 660), "yeniden canlandırma", font=sans, fill=(110, 102, 90))
    clip = blend_grain(clip, f"{seed}:news-paper", alpha=0.08)
    rotated = clip.rotate(
        -2.4,
        expand=True,
        resample=Image.Resampling.BICUBIC,
        fillcolor=(38, 32, 26),
    )
    xy = (220, 70)
    paste_shadow(canvas, rotated.convert("RGBA"), xy, offset=(12, 14))
    canvas.paste(rotated, xy)
    return blend_grain(canvas, f"{seed}:news-final", alpha=0.04), fields, "newspaper_clipping"
