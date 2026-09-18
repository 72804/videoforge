from __future__ import annotations

import re
import unicodedata

from docprod.models.scene import Scene

_WORD_RE = re.compile(r"[\wğüşöçıİĞÜŞÖÇ]+", re.UNICODE)

_TERM_EN: dict[str, tuple[str, ...]] = {
    "tren istasyonu": ("train station", "railway station"),
    "istasyon": ("train station", "railway station", "station platform"),
    "tren": ("train", "commuter train"),
    "akşam": ("evening", "dusk"),
    "boş": ("empty", "quiet"),
    "neredeyse boştu": ("empty",),
    "çıkış": ("station exit", "exit"),
    "kuzey": ("north",),
    "telefon": ("phone", "mobile phone"),
    "koşarak": ("walking", "running"),
    "gitti": ("walking",),
    "araba": ("car", "automobile"),
    "fren": ("braking", "car stopping"),
    "ani fren": ("car braking", "sudden stop"),
    "vagon": ("train carriage",),
    "peron": ("platform",),
}

_STOP = frozenset(
    {
        "bir",
        "ve",
        "ile",
        "doğru",
        "saatlerinde",
        "saat",
        "içindeki",
        "önünde",
        "yaptı",
        "açtı",
        "gitti",
        "neredeyse",
    }
)

_CATEGORY_QUERIES: dict[str, tuple[str, ...]] = {
    "location_establishing": ("establishing city location",),
    "vehicle": ("car driving city",),
    "map_or_travel": ("travel transit",),
    "police": ("police street",),
}


def _fold(text: str) -> str:
    swapped = text.replace("İ", "i").replace("I", "i").replace("ı", "i")
    stripped = "".join(
        char for char in unicodedata.normalize("NFKD", swapped) if not unicodedata.combining(char)
    )
    return stripped.casefold()


def _tokens(text: str) -> list[str]:
    return [token.lower() for token in _WORD_RE.findall(text)]


def _english_phrases(scene: Scene) -> list[str]:
    blob = (
        f"{scene.narration} {scene.visual_intent} "
        f"{' '.join(scene.metadata.get('matched_terms') or [])}"
    )
    lowered = _fold(blob)
    phrases: list[str] = []
    for term, english in sorted(_TERM_EN.items(), key=lambda item: -len(item[0])):
        if _fold(term) in lowered:
            for item in english:
                if item not in phrases:
                    phrases.append(item)
    return phrases


def generate_stock_queries(scene: Scene, *, max_queries: int = 4) -> list[str]:
    """Short English visual queries. No LLM. Not a full-narration dump."""
    phrases = _english_phrases(scene)
    blob = _fold(f"{scene.narration} {scene.visual_intent}")
    queries: list[str] = []

    def add(query: str) -> None:
        cleaned = re.sub(r"\s+", " ", query).strip()
        if cleaned and cleaned.lower() not in {item.lower() for item in queries}:
            if len(queries) < max_queries:
                queries.append(cleaned)

    vehicle = any(term in phrases for term in ("car", "automobile", "braking", "car stopping"))
    motion = any(term in phrases for term in ("walking", "running", "phone", "station exit"))
    station = any(
        term in phrases
        for term in ("train station", "railway station", "station platform")
    )

    if vehicle:
        add("car braking street")
        add("car stopping in front of station")
        add("car driving city")
        add("car sudden stop street")
    elif motion and station:
        add("man walking train station")
        add("station exit")
        add("commuter using phone station")
        add("person walking railway station")
    elif station:
        if "empty" in phrases or "boş" in blob:
            add("empty train station evening")
        add("train station platform")
        add("railway station")
        add("commuter train platform")

    category = str(scene.metadata.get("primary_category") or "")
    for extra in _CATEGORY_QUERIES.get(category, ()):
        add(extra)
    if not queries:
        nouns = [token for token in _tokens(scene.narration) if token not in _STOP]
        add(" ".join(nouns[:4]) or "documentary street")
    return queries[:max_queries]
