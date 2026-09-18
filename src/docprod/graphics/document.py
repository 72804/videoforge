from __future__ import annotations

import hashlib
from collections.abc import Sequence

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from docprod.graphics import GRAPHIC_HEIGHT, GRAPHIC_WIDTH
from docprod.graphics.fonts import discover_mono_font, discover_sans_font, load_font
from docprod.models.scene import Scene


def strip_visual_boilerplate(text: str) -> str:
    prefixes = (
        "documentary close-up of a document or record representing:",
        "documentary insert of news or press material representing:",
        "documentary visual representing:",
        "documentary map or travel graphic representing:",
    )
    current = text.strip()
    lowered = current.lower()
    for prefix in prefixes:
        if lowered.startswith(prefix):
            return current[len(prefix) :].strip(" :")
    return current


def scene_fact_line(scene: Scene) -> str:
    narration = scene.narration.strip()
    intent = strip_visual_boilerplate(scene.visual_intent)
    if intent and intent.lower() not in narration.lower():
        return f"{narration} {intent}".strip()
    return narration


def wrap_text(text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    words = text.split()
    if not words:
        return []
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        trial = f"{current} {word}"
        if font.getlength(trial) <= max_width:
            current = trial
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def deterministic_grain(size: tuple[int, int], seed: str, *, opacity: int = 28) -> Image.Image:
    width, height = 96, 54
    needed = width * height
    payload = bytearray()
    counter = 0
    key = seed.encode("utf-8")
    while len(payload) < needed:
        payload.extend(hashlib.sha256(key + counter.to_bytes(4, "little")).digest())
        counter += 1
    small = Image.frombytes("L", (width, height), bytes(payload[:needed]))
    grain = small.resize(size, Image.Resampling.BILINEAR)
    return ImageOps.colorize(grain, (0, 0, 0), (255, 255, 255)).convert("RGB")


def blend_grain(base: Image.Image, seed: str, *, alpha: float = 0.07) -> Image.Image:
    grain = deterministic_grain(base.size, seed)
    return Image.blend(base.convert("RGB"), grain, alpha)


def desk_background(size: tuple[int, int], seed: str) -> Image.Image:
    width, height = size
    image = Image.new("RGB", size, (38, 32, 26))
    draw = ImageDraw.Draw(image)
    for index in range(0, height, 7):
        tone = 34 + (index * 3 + len(seed)) % 10
        draw.line((0, index, width, index), fill=(tone, tone - 6, tone - 10))
    return blend_grain(image, f"{seed}:desk", alpha=0.08)


def paper_sheet(
    size: tuple[int, int],
    seed: str,
    *,
    color: tuple[int, int, int] = (243, 234, 214),
) -> Image.Image:
    sheet = Image.new("RGB", size, color)
    draw = ImageDraw.Draw(sheet)
    draw.rectangle((0, 0, size[0] - 1, size[1] - 1), outline=(210, 198, 172))
    return blend_grain(sheet, f"{seed}:paper", alpha=0.05)


def paste_shadow(
    canvas: Image.Image,
    sheet: Image.Image,
    xy: tuple[int, int],
    *,
    offset: tuple[int, int] = (10, 12),
) -> None:
    shadow = Image.new("RGBA", sheet.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rectangle((0, 0, sheet.size[0], sheet.size[1]), fill=(0, 0, 0, 90))
    shadow = shadow.filter(ImageFilter.GaussianBlur(8))
    canvas.paste(shadow, (xy[0] + offset[0], xy[1] + offset[1]), shadow)


def redact_bar(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int]) -> None:
    draw.rectangle(box, fill=(22, 22, 22))


def photo_placeholder(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    caption: str,
    font: ImageFont.ImageFont,
) -> None:
    draw.rectangle(box, fill=(48, 46, 42), outline=(90, 86, 78))
    cx = (box[0] + box[2]) // 2
    cy = (box[1] + box[3]) // 2
    draw.rectangle((cx - 28, cy - 18, cx + 28, cy + 22), outline=(160, 154, 140), width=2)
    draw.text((box[0] + 8, box[3] - 22), caption, font=font, fill=(180, 174, 160))


def classify_document_layout(scene: Scene) -> str:
    text = f"{scene.narration} {scene.visual_intent}".lower()
    category = str(scene.metadata.get("primary_category") or "").lower()
    if "gazete" in text or "kupür" in text or category == "news":
        return "newspaper"
    if "mahkeme" in text or category == "court_or_legal":
        return "court_folder"
    return "police_report"


def render_police_report(scene: Scene, *, seed: str) -> tuple[Image.Image, dict[str, str]]:
    sans = load_font(discover_sans_font(), 22)
    mono = load_font(discover_mono_font(), 20)
    heading = load_font(discover_sans_font(), 34)
    small = load_font(discover_sans_font(), 16)
    canvas = desk_background((GRAPHIC_WIDTH, GRAPHIC_HEIGHT), seed)
    sheet = paper_sheet((980, 720), seed)
    draw = ImageDraw.Draw(sheet)
    fields = {
        "heading": "OLAY RAPORU",
        "case_ref": "CASE REF: 0042",
        "agency": "Kurum içi kayıt — yeniden canlandırma",
        "fact": scene.narration.strip(),
        "stamp": "İNCELEME",
    }
    draw.rectangle((36, 28, 944, 96), outline=(90, 78, 62), width=2)
    draw.text((52, 40), fields["heading"], font=heading, fill=(32, 28, 22))
    draw.text((52, 78), fields["agency"], font=small, fill=(90, 82, 70))
    draw.text((680, 46), fields["case_ref"], font=mono, fill=(50, 44, 36))
    y = 128
    labels = (
        ("Konu", "Çanta içi rapor / polis bildirimi"),
        ("Özet", scene.narration.strip()),
        ("Not", "Kimlik ve dosya numarası reddedildi."),
    )
    for label, value in labels:
        draw.text((52, y), f"{label}:", font=sans, fill=(70, 62, 52))
        if label == "Not":
            redact_bar(draw, (150, y + 2, 430, y + 22))
            draw.text((150, y), "████████", font=mono, fill=(22, 22, 22))
        else:
            for line in wrap_text(value, mono, 860)[:4]:
                draw.text((150, y), line, font=mono, fill=(28, 24, 20))
                y += 26
            y += 8
            continue
        y += 40
    photo_placeholder(draw, (52, 430, 300, 640), "kanıt fotoğrafı", small)
    draw.rectangle((340, 430, 920, 640), outline=(180, 168, 148))
    body_lines = wrap_text(
        "Rapor metni sahne anlatımıyla sınırlıdır. Ek resmi iddia üretilmedi.",
        mono,
        540,
    )
    by = 448
    for line in body_lines:
        draw.text((356, by), line, font=mono, fill=(40, 36, 30))
        by += 26
    stamp = Image.new("RGBA", (220, 80), (0, 0, 0, 0))
    ImageDraw.Draw(stamp).ellipse((4, 4, 216, 76), outline=(140, 48, 42, 170), width=3)
    ImageDraw.Draw(stamp).text((38, 26), fields["stamp"], font=sans, fill=(140, 48, 42, 170))
    stamp = stamp.rotate(12, expand=True, resample=Image.Resampling.BICUBIC)
    sheet = sheet.convert("RGBA")
    sheet.alpha_composite(stamp, (700, 520))
    sheet = sheet.convert("RGB")
    xy = (240, 60)
    paste_shadow(canvas, sheet.convert("RGBA"), xy)
    canvas.paste(sheet, xy)
    mark = load_font(discover_sans_font(), 13)
    ImageDraw.Draw(canvas).text(
        (24, GRAPHIC_HEIGHT - 28),
        "yeniden canlandırma grafiği",
        font=mark,
        fill=(160, 150, 138),
    )
    return blend_grain(canvas, f"{seed}:final", alpha=0.03), fields


def render_court_folder(scene: Scene, *, seed: str) -> tuple[Image.Image, dict[str, str]]:
    sans = load_font(discover_sans_font(), 22)
    mono = load_font(discover_mono_font(), 19)
    heading = load_font(discover_sans_font(), 30)
    small = load_font(discover_sans_font(), 15)
    canvas = desk_background((GRAPHIC_WIDTH, GRAPHIC_HEIGHT), f"{seed}:court")
    folder = Image.new("RGB", (1080, 700), (122, 86, 48))
    fdraw = ImageDraw.Draw(folder)
    fdraw.polygon(
        [(0, 70), (220, 70), (260, 0), (1080, 0), (1080, 700), (0, 700)],
        fill=(132, 94, 52),
    )
    fdraw.polygon([(0, 70), (220, 70), (260, 0), (520, 0), (480, 70)], fill=(148, 108, 64))
    inner = paper_sheet((920, 560), f"{seed}:court-paper", color=(248, 244, 232))
    idraw = ImageDraw.Draw(inner)
    fields = {
        "heading": "DOSYA NOTU",
        "tab": "MAHKEME",
        "missing": "Mahkeme tutanağı: mevcut değil",
        "fact": scene.narration.strip(),
        "stamp": "GÖRÜLDÜ",
    }
    fdraw.text((48, 22), fields["tab"], font=heading, fill=(250, 244, 230))
    idraw.text((40, 28), fields["heading"], font=heading, fill=(36, 32, 26))
    idraw.line((40, 72, 880, 72), fill=(80, 70, 58), width=2)
    idraw.text((40, 92), fields["missing"], font=sans, fill=(90, 36, 28))
    y = 140
    for line in wrap_text(fields["fact"], mono, 820)[:6]:
        idraw.text((40, y), line, font=mono, fill=(32, 28, 24))
        y += 28
    idraw.text((40, 360), "İmza / paraf", font=small, fill=(90, 82, 70))
    idraw.line((40, 410, 360, 410), fill=(50, 44, 38), width=1)
    redact_bar(idraw, (420, 392, 700, 412))
    idraw.rectangle((40, 450, 880, 530), outline=(170, 160, 140))
    idraw.text(
        (52, 468),
        "Ek: yalnızca mevcut rapor. Resmi tutanak eklenmedi.",
        font=mono,
        fill=(50, 46, 40),
    )
    stamp = Image.new("RGBA", (200, 70), (0, 0, 0, 0))
    ImageDraw.Draw(stamp).rectangle((6, 6, 194, 64), outline=(42, 82, 58, 180), width=3)
    ImageDraw.Draw(stamp).text((42, 22), fields["stamp"], font=sans, fill=(42, 82, 58, 180))
    stamp = stamp.rotate(-8, expand=True, resample=Image.Resampling.BICUBIC)
    inner = inner.convert("RGBA")
    inner.alpha_composite(stamp, (680, 330))
    folder = folder.convert("RGBA")
    folder.alpha_composite(inner, (70, 96))
    clip = Image.new("RGBA", (50, 90), (0, 0, 0, 0))
    ImageDraw.Draw(clip).rounded_rectangle(
        (8, 8, 40, 80),
        radius=12,
        outline=(170, 170, 176, 230),
        width=4,
    )
    folder.alpha_composite(clip, (40, 80))
    folder_rgb = folder.convert("RGB")
    xy = (210, 70)
    paste_shadow(canvas, folder.convert("RGBA"), xy, offset=(14, 16))
    canvas.paste(folder_rgb, xy)
    mark = load_font(discover_sans_font(), 13)
    ImageDraw.Draw(canvas).text(
        (24, GRAPHIC_HEIGHT - 28),
        "yeniden canlandırma grafiği",
        font=mark,
        fill=(160, 150, 138),
    )
    return blend_grain(canvas, f"{seed}:court-final", alpha=0.03), fields


def render_document_graphic(scene: Scene, *, seed: str) -> tuple[Image.Image, dict[str, str], str]:
    layout = classify_document_layout(scene)
    if layout == "court_folder":
        image, fields = render_court_folder(scene, seed=seed)
        return image, fields, layout
    image, fields = render_police_report(scene, seed=seed)
    return image, fields, layout


FORBIDDEN_MARKERS: Sequence[str] = (
    "T.C.",
    "Emniyet Genel Müdürlüğü",
    "Jandarma",
    "Resmi Gazete",
    "FAKE DOCUMENT",
)
