from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from docprod.graphics import TURKISH_SAMPLE

_SANS = (
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
)
_SERIF = (
    "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
    "/Library/Fonts/Times New Roman.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
)
_MONO = (
    "/System/Library/Fonts/Supplemental/Courier New.ttf",
    "/Library/Fonts/Courier New.ttf",
    "/System/Library/Fonts/Menlo.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
)


def font_renders_turkish(path: Path, *, size: int = 32) -> bool:
    try:
        font = ImageFont.truetype(str(path), size=size)
    except OSError:
        return False
    image = Image.new("L", (720, 64), 0)
    ImageDraw.Draw(image).text((4, 8), TURKISH_SAMPLE, font=font, fill=255)
    return image.getextrema()[1] > 32


def _first_usable(candidates: tuple[str, ...]) -> Path:
    for raw in candidates:
        path = Path(raw)
        if path.is_file() and font_renders_turkish(path):
            return path
    raise FileNotFoundError(
        "No Turkish-capable system font found. Install Arial, Times New Roman, or DejaVu."
    )


@lru_cache
def discover_sans_font() -> Path:
    return _first_usable(_SANS)


@lru_cache
def discover_serif_font() -> Path:
    try:
        return _first_usable(_SERIF)
    except FileNotFoundError:
        return discover_sans_font()


@lru_cache
def discover_mono_font() -> Path:
    try:
        return _first_usable(_MONO)
    except FileNotFoundError:
        return discover_sans_font()


def load_font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), size=size)
