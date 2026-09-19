from __future__ import annotations

import math

from PIL import Image, ImageDraw

from docprod.graphics import GRAPHIC_HEIGHT, GRAPHIC_WIDTH
from docprod.graphics.document import blend_grain, wrap_text
from docprod.graphics.fonts import discover_sans_font, load_font
from docprod.models.scene import Scene

ROUTE: list[tuple[int, int]] = [
    (220, 680),
    (220, 430),
    (510, 430),
    (510, 250),
    (1180, 250),
    (1280, 180),
]
ORIGIN = ROUTE[0]
DEST = ROUTE[-1]


def map_labels(scene: Scene) -> dict[str, str]:
    if use_story_geography(scene):
        return {
            "title": "Soruşturma coğrafyası",
            "origin": "Quebec",
            "destination": "Bölgesel ilişki",
            "fact": scene.narration.strip(),
            "note": "Konumlar yaklaşıktır. Kesin sevkiyat güzergahı bilinmiyor; rota uydurulmadı.",
        }
    return {
        "title": "Şematik rota",
        "origin": "A",
        "destination": "Kuzey Kapısı",
        "fact": scene.narration.strip(),
        "note": "Kesin coğrafya bilinmiyor; şema anlatıya bağlıdır.",
    }


def use_story_geography(scene: Scene) -> bool:
    blob = f"{scene.narration} {scene.visual_intent} {scene.metadata.get('graphic_brief') or ''}"
    lowered = blob.casefold()
    return any(
        token in lowered
        for token in (
            "quebec",
            "kedgwick",
            "blandford",
            "ontario",
            "laurierville",
            "new brunswick",
        )
    )


def _draw_grid(draw: ImageDraw.ImageDraw, *, width: int, height: int) -> None:
    color = (42, 52, 60)
    for x in range(80, width, 80):
        draw.line((x, 0, x, height), fill=color)
    for y in range(60, height, 60):
        draw.line((0, y, width, y), fill=color)
    rail = (58, 72, 82)
    draw.line((140, 40, 140, height - 40), fill=rail, width=5)
    draw.line((140, height // 2, width - 80, height // 2), fill=rail, width=3)


def _polyline_length(points: list[tuple[int, int]]) -> float:
    total = 0.0
    for start, end in zip(points, points[1:], strict=False):
        total += ((end[0] - start[0]) ** 2 + (end[1] - start[1]) ** 2) ** 0.5
    return total


def _point_at(points: list[tuple[int, int]], distance: float) -> tuple[int, int]:
    remaining = distance
    for start, end in zip(points, points[1:], strict=False):
        span = ((end[0] - start[0]) ** 2 + (end[1] - start[1]) ** 2) ** 0.5
        if span <= 1e-6:
            continue
        if remaining <= span:
            t = remaining / span
            return (
                int(start[0] + (end[0] - start[0]) * t),
                int(start[1] + (end[1] - start[1]) * t),
            )
        remaining -= span
    return points[-1]


def draw_route_mask(size: tuple[int, int], *, width: int = 10) -> Image.Image:
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    total = _polyline_length(ROUTE)
    steps = 180
    for index in range(steps):
        dist = total * (index + 1) / steps
        point = _point_at(ROUTE, dist)
        level = max(12, int(255 * (index + 1) / steps))
        r = width
        draw.ellipse((point[0] - r, point[1] - r, point[0] + r, point[1] + r), fill=level)
    return mask


def draw_route_overlay(size: tuple[int, int]) -> Image.Image:
    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw.line(ROUTE, fill=(196, 92, 62, 255), width=8)
    return overlay


def draw_map_background(scene: Scene, *, seed: str) -> tuple[Image.Image, dict[str, str]]:
    labels = map_labels(scene)
    if use_story_geography(scene):
        return _draw_relationship_map(scene, labels, seed=seed)
    image = Image.new("RGB", (GRAPHIC_WIDTH, GRAPHIC_HEIGHT), (18, 24, 28))
    draw = ImageDraw.Draw(image)
    _draw_grid(draw, width=GRAPHIC_WIDTH, height=GRAPHIC_HEIGHT)
    # Unnamed nodes keep the schematic from inventing extra places.
    for point in ((220, 680), (510, 430), (900, 430), (1180, 250)):
        draw.ellipse((point[0] - 6, point[1] - 6, point[0] + 6, point[1] + 6), fill=(150, 158, 164))
    sans = load_font(discover_sans_font(), 22)
    small = load_font(discover_sans_font(), 16)
    title = load_font(discover_sans_font(), 28)
    draw.text((40, 28), labels["title"], font=title, fill=(214, 208, 196))
    draw.text((40, 68), labels["note"], font=small, fill=(140, 148, 154))
    draw.ellipse(
        (ORIGIN[0] - 10, ORIGIN[1] - 10, ORIGIN[0] + 10, ORIGIN[1] + 10),
        fill=(214, 208, 196),
    )
    draw.text((ORIGIN[0] + 16, ORIGIN[1] - 14), labels["origin"], font=sans, fill=(230, 224, 214))
    draw.ellipse(
        (DEST[0] - 12, DEST[1] - 12, DEST[0] + 12, DEST[1] + 12),
        outline=(196, 92, 62),
        width=3,
    )
    dest_lines = wrap_text(labels["destination"], sans, 280)
    draw.text((DEST[0] - 180, DEST[1] - 40), dest_lines[0], font=sans, fill=(230, 224, 214))
    image = blend_grain(image, f"{seed}:map", alpha=0.05)
    return image, labels


STORY_NODES = (
    ("Quebec", 520, 420),
    ("Saint-Louis-de-Blandford", 380, 480),
    ("Kedgwick", 820, 220),
    ("Ontario", 240, 360),
    ("ABD", 980, 520),
)


def _draw_relationship_map(
    scene: Scene, labels: dict[str, str], *, seed: str
) -> tuple[Image.Image, dict[str, str]]:
    image = Image.new("RGB", (GRAPHIC_WIDTH, GRAPHIC_HEIGHT), (18, 24, 28))
    draw = ImageDraw.Draw(image)
    _draw_grid(draw, width=GRAPHIC_WIDTH, height=GRAPHIC_HEIGHT)
    sans = load_font(discover_sans_font(), 20)
    small = load_font(discover_sans_font(), 16)
    title = load_font(discover_sans_font(), 28)
    draw.text((40, 28), labels["title"], font=title, fill=(214, 208, 196))
    draw.text((40, 68), labels["note"], font=small, fill=(140, 148, 154))
    blob = f"{scene.narration} {scene.visual_intent}".casefold()
    for name, x, y in STORY_NODES:
        if name == "ABD" and "amerika" not in blob and "united" not in blob and "abd" not in blob:
            continue
        if name == "Kedgwick" and "kedgwick" not in blob and "brunswick" not in blob:
            continue
        if name == "Ontario" and "ontario" not in blob:
            continue
        draw.ellipse((x - 8, y - 8, x + 8, y + 8), fill=(196, 92, 62))
        draw.text((x + 14, y - 12), name, font=sans, fill=(230, 224, 214))
    image = blend_grain(image, f"{seed}:geomap", alpha=0.05)
    return image, labels


def compose_map_still(
    scene: Scene, *, seed: str
) -> tuple[Image.Image, Image.Image, Image.Image, Image.Image, dict[str, str]]:
    background, labels = draw_map_background(scene, seed=seed)
    if use_story_geography(scene):
        empty = Image.new("RGBA", background.size, (0, 0, 0, 0))
        mask = Image.new("L", background.size, 0)
        return background, background, empty, mask, labels
    overlay = draw_route_overlay(background.size)
    mask = draw_route_mask(background.size)
    still = background.convert("RGBA")
    still.alpha_composite(overlay)
    return still.convert("RGB"), background, overlay, mask, labels


def route_reveal(progress: float) -> float:
    """0–20% hidden, 20–80% linear draw, 80–100% complete."""
    if progress <= 0.20:
        return 0.0
    if progress >= 0.80:
        return 1.0
    return (progress - 0.20) / 0.60


def map_overlay_filter(*, duration: float, dest: tuple[int, int]) -> str:
    """Reveal route via luminance mask. `t` is seconds."""
    dur = max(duration, 0.001)
    t0 = 0.2 * dur
    t1 = 0.8 * dur
    span = max(t1 - t0, 0.001)
    prog = f"min(1\\,max(0\\,(t-{t0:.4f})/{span:.4f}))"
    alpha = (
        f"if(eq(lum(X\\,Y)\\,0)\\,0\\,if(lte(lum(X\\,Y)\\,255*{prog})\\,255\\,0))"
    )
    pulse = f"if(lt(t\\,{t1:.4f})\\,0\\,0.55+0.45*sin(2*PI*t*1.6))"
    return (
        f"[2:v]format=gray,geq=lum='lum(X\\,Y)':a='{alpha}':eval=frame[mask];"
        f"[1:v][mask]alphamerge[route];"
        f"[0:v][route]overlay=0:0[mapped];"
        f"[mapped][3:v]overlay={dest[0] - 18}:{dest[1] - 18}:alpha='{pulse}'[vout]"
    )


def dest_ring_image() -> Image.Image:
    ring = Image.new("RGBA", (36, 36), (0, 0, 0, 0))
    ImageDraw.Draw(ring).ellipse((2, 2, 33, 33), outline=(220, 120, 90, 255), width=3)
    return ring


def composite_map_frame(
    background: Image.Image,
    overlay: Image.Image,
    mask: Image.Image,
    *,
    progress: float,
) -> Image.Image:

    reveal = route_reveal(progress)
    threshold = int(reveal * 255)
    lut = [255 if 0 < value <= threshold else 0 for value in range(256)]
    alpha = mask.point(lut)
    route = overlay.convert("RGBA")
    route.putalpha(alpha)
    frame = background.convert("RGBA")
    frame.alpha_composite(route)
    pulse = 0.0 if progress < 0.80 else 0.55 + 0.45 * math.sin(progress * 40)
    if pulse > 0:
        faded = dest_ring_image()
        faded.putalpha(faded.getchannel("A").point(lambda p, scale=pulse: int(p * scale)))
        frame.alpha_composite(faded, (DEST[0] - 18, DEST[1] - 18))
    return frame.convert("RGB")
