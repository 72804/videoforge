from __future__ import annotations

from PIL import Image, ImageDraw

from docprod.graphics import GRAPHIC_HEIGHT, GRAPHIC_WIDTH
from docprod.graphics.document import wrap_text
from docprod.graphics.fonts import discover_sans_font, load_font
from docprod.models.scene import Scene

INFO_GRAPHIC_KINDS = {
    "au_0033": "barrel_uncertainty",
    "au_0034": "trade_flow",
    "au_0044": "arrest_compare",
    "au_0051": "court_stages",
}


def info_graphic_kind(scene: Scene) -> str | None:
    kind = str(scene.metadata.get("graphic_kind") or "")
    if kind in INFO_GRAPHIC_KINDS.values():
        return kind
    unit = str(scene.metadata.get("asset_unit_id") or "")
    return INFO_GRAPHIC_KINDS.get(unit)


def _canvas() -> Image.Image:
    image = Image.new("RGB", (GRAPHIC_WIDTH, GRAPHIC_HEIGHT), (18, 20, 24))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, GRAPHIC_WIDTH, 8), fill=(196, 160, 72))
    return image


def render_info_graphic(scene: Scene) -> tuple[Image.Image, dict[str, str], str]:
    kind = info_graphic_kind(scene) or "barrel_uncertainty"
    if kind == "trade_flow":
        return _trade_flow()
    if kind == "arrest_compare":
        return _arrest_compare()
    if kind == "court_stages":
        return _court_stages()
    return _barrel_uncertainty()


def _barrel_uncertainty() -> tuple[Image.Image, dict[str, str], str]:
    image = _canvas()
    draw = ImageDraw.Draw(image)
    title = load_font(discover_sans_font(), 42)
    body = load_font(discover_sans_font(), 28)
    small = load_font(discover_sans_font(), 22)
    draw.text((72, 48), "Fıçı sayısı — belirsizlik", font=title, fill=(236, 232, 220))
    draw.text(
        (72, 118),
        "Kaynaklara göre kesin bir toplam yayınlanmadı.",
        font=body,
        fill=(200, 196, 184),
    )
    xs = [180, 340, 500, 660, 820, 980, 1140, 1300]
    for index, x in enumerate(xs):
        fill = (70, 74, 82) if index % 2 else (52, 56, 64)
        draw.ellipse((x, 430, x + 90, 500), fill=fill)
        draw.rectangle((x + 8, 260, x + 82, 450), fill=fill)
        draw.ellipse((x, 230, x + 90, 290), fill=(90, 94, 102))
    draw.text(
        (72, 560),
        "Silüetler temsili. Sayı uydurulmadı.",
        font=small,
        fill=(168, 164, 150),
    )
    draw.text((72, 620), "Kaynaklara göre: aralık / belirsiz", font=body, fill=(214, 186, 110))
    fields = {
        "heading": "Fıçı sayısı — belirsizlik",
        "note": "Kaynaklara göre kesin bir toplam yayınlanmadı.",
    }
    return image, fields, "barrel_uncertainty"


def _trade_flow() -> tuple[Image.Image, dict[str, str], str]:
    image = _canvas()
    draw = ImageDraw.Draw(image)
    title = load_font(discover_sans_font(), 40)
    body = load_font(discover_sans_font(), 26)
    draw.text((72, 48), "Depo / işleme / ticaret kanalı", font=title, fill=(236, 232, 220))
    boxes = (
        (80, 280, 420, 520, "Depo"),
        (560, 280, 900, 520, "İşleme"),
        (1040, 280, 1450, 520, "Ticaret kanalı"),
    )
    for x0, y0, x1, y1, label in boxes:
        draw.rounded_rectangle((x0, y0, x1, y1), radius=18, outline=(196, 160, 72), width=3)
        draw.text((x0 + 36, y0 + 90), label, font=title, fill=(230, 226, 214))
    for x in (430, 910):
        draw.polygon([(x, 380), (x + 110, 400), (x, 420)], fill=(196, 160, 72))
    draw.text(
        (72, 620),
        "Oklar isimsiz. Güzergâh uydurulmadı.",
        font=body,
        fill=(168, 164, 150),
    )
    fields = {
        "heading": "Depo / işleme / ticaret kanalı",
        "note": "Oklar isimsiz. Güzergâh uydurulmadı.",
    }
    return image, fields, "trade_flow"


def _arrest_compare() -> tuple[Image.Image, dict[str, str], str]:
    image = _canvas()
    draw = ImageDraw.Draw(image)
    title = load_font(discover_sans_font(), 40)
    body = load_font(discover_sans_font(), 28)
    big = load_font(discover_sans_font(), 72)
    draw.text((72, 48), "Tutuklama sayısı — karşılaştırma", font=title, fill=(236, 232, 220))
    draw.text((72, 118), "Kaynaklara göre iki farklı çerçeve", font=body, fill=(200, 196, 184))
    draw.rounded_rectangle((120, 240, 700, 620), radius=16, outline=(140, 150, 168), width=3)
    draw.rounded_rectangle((836, 240, 1416, 620), radius=16, outline=(196, 160, 72), width=3)
    draw.text((280, 280), "Kaynak A", font=body, fill=(180, 186, 196))
    draw.text((1020, 280), "Kaynak B", font=body, fill=(214, 186, 110))
    draw.text((300, 380), "16", font=big, fill=(236, 232, 220))
    draw.text((920, 380), "yaklaşık 26", font=big, fill=(236, 232, 220))
    draw.text((160, 540), "Kesin tek rakam yok", font=body, fill=(168, 164, 150))
    draw.text((900, 540), "16 / yaklaşık 26", font=body, fill=(168, 164, 150))
    fields = {
        "heading": "Tutuklama sayısı — karşılaştırma",
        "left": "16",
        "right": "yaklaşık 26",
        "note": "Kaynaklara göre iki farklı çerçeve",
    }
    return image, fields, "arrest_compare"


def _court_stages() -> tuple[Image.Image, dict[str, str], str]:
    image = _canvas()
    draw = ImageDraw.Draw(image)
    title = load_font(discover_sans_font(), 40)
    body = load_font(discover_sans_font(), 28)
    draw.text((72, 48), "Temyiz süreci — iki aşama", font=title, fill=(236, 232, 220))
    draw.rounded_rectangle((120, 260, 700, 560), radius=16, outline=(196, 160, 72), width=3)
    draw.rounded_rectangle((836, 260, 1416, 560), radius=16, outline=(196, 160, 72), width=3)
    draw.text((180, 320), "1. Québec temyiz", font=title, fill=(236, 232, 220))
    draw.text((900, 320), "2. Yüksek mahkeme", font=title, fill=(236, 232, 220))
    draw.polygon([(710, 380), (820, 400), (710, 420)], fill=(196, 160, 72))
    note = "Aşamalar temsili. Karar metni uydurulmadı."
    for line in wrap_text(note, body, 1300):
        draw.text((72, 640), line, font=body, fill=(168, 164, 150))
    fields = {
        "heading": "Temyiz süreci — iki aşama",
        "stage_1": "Québec temyiz",
        "stage_2": "Yüksek mahkeme",
        "note": note,
    }
    return image, fields, "court_stages"
