from __future__ import annotations

import re
import unicodedata

_WORD_RE = re.compile(r"[\wğüşöçıİĞÜŞÖÇ'\-]+", re.UNICODE)

_MONTHS = {
    "ocak",
    "subat",
    "şubat",
    "mart",
    "nisan",
    "mayis",
    "mayıs",
    "haziran",
    "temmuz",
    "agustos",
    "ağustos",
    "eylul",
    "eylül",
    "ekim",
    "kasim",
    "kasım",
    "aralik",
    "aralık",
}

_CURRENCIES = {
    "kanada",
    "dolar",
    "dolari",
    "doları",
    "dolarina",
    "dolarına",
    "pound",
    "sterlin",
    "euro",
}

_UNITS = {
    "milyon",
    "bin",
    "pound",
    "dolar",
    "dolari",
    "doları",
    "dolarina",
    "dolarına",
    "sent",
    "sentlik",
    "cent",
    "yil",
    "yıl",
    "yıla",
    "gun",
    "gün",
    "kg",
    "ton",
    "adet",
    "fici",
    "fıçı",
    "ficiyla",
}

_NAME_PARTICLES = {"st", "saint", "van", "de", "du", "le", "la", "el"}

_ABBREV = {
    "dr",
    "mr",
    "mrs",
    "ms",
    "prof",
    "vs",
    "no",
    "sn",
    "st",
    "vd",
    "vb",
    "örn",
    "orn",
    "etc",
}


def _fold(text: str) -> str:
    swapped = text.replace("İ", "i").replace("I", "i").replace("ı", "i")
    stripped = "".join(
        char for char in unicodedata.normalize("NFKD", swapped) if not unicodedata.combining(char)
    )
    return re.sub(r"[^\w]+", "", stripped, flags=re.UNICODE).casefold()


_MONTHS = {_fold(item) for item in _MONTHS}
_UNITS = {_fold(item) for item in _UNITS}
_CURRENCIES = {_fold(item) for item in _CURRENCIES}
_NAME_PARTICLES = {_fold(item) for item in _NAME_PARTICLES}
_ABBREV = {_fold(item) for item in _ABBREV}


def _is_year(token: str) -> bool:
    digits = re.sub(r"\D", "", token)
    return len(digits) == 4 and digits.startswith(("19", "20"))


def _is_number(token: str) -> bool:
    folded = _fold(token)
    if folded.isdigit():
        return True
    return folded in {
        "iki",
        "uc",
        "üç",
        "dort",
        "dört",
        "bes",
        "beş",
        "alti",
        "altı",
        "yedi",
        "sekiz",
        "dokuz",
        "on",
    }


def _looks_name(token: str) -> bool:
    cleaned = token.strip("-'")
    if len(cleaned) < 2:
        return False
    if cleaned[0].isupper() and any(char.islower() for char in cleaned[1:]):
        return True
    return _fold(cleaned) in _NAME_PARTICLES


def _words(text: str) -> list[tuple[int, int, str]]:
    return [(match.start(), match.end(), match.group(0)) for match in _WORD_RE.finditer(text)]


class NarrationBoundaryValidator:
    """Reject syntactically unsafe TTS chunk splits. Chapter metadata is not enough."""

    def reason(self, text: str, split: int) -> str | None:
        if split <= 0 or split >= len(text):
            return None
        if text[split - 1].isalnum() and split < len(text) and text[split].isalnum():
            return "mid_word"
        left = [item for item in _words(text[:split])[-4:]]
        right = [item for item in _words(text[split:])[:4]]
        left_tok = [item[2] for item in left]
        right_tok = [item[2] for item in right]
        if not left_tok or not right_tok:
            return None
        lf = [_fold(item) for item in left_tok]
        rf = [_fold(item) for item in right_tok]
        if lf[-1] in _MONTHS and _is_year(right_tok[0]):
            return "date_phrase"
        if _is_number(left_tok[-1]) and lf[-1] not in _MONTHS and rf[0] in _MONTHS:
            return "date_phrase"
        if (
            len(lf) >= 2
            and _is_number(left_tok[-2])
            and lf[-1] in _MONTHS
            and _is_year(right_tok[0])
        ):
            return "date_phrase"
        if _is_number(left_tok[-1]) and rf[0] in _UNITS:
            return "number_unit"
        if lf[-1] in _UNITS and rf[0] in _UNITS.union(_CURRENCIES):
            return "number_unit"
        if lf[-1] in _UNITS and rf[0] in {"kadar", "yani"}:
            return "number_unit"
        if len(lf) >= 2 and _is_number(left_tok[-2]) and lf[-1] in _UNITS and rf[0] in _CURRENCIES:
            return "number_unit"
        if lf[-1] in _NAME_PARTICLES and _looks_name(right_tok[0]):
            return "full_name"
        if _looks_name(left_tok[-1]) and _looks_name(right_tok[0]) and lf[-1] not in _MONTHS:
            return "full_name"
        if _looks_name(left_tok[-1]) and right_tok[0][:1].islower():
            return "noun_phrase"
        if lf[-1] in _ABBREV:
            return "abbreviation"
        quotes = text[:split]
        if quotes.count('"') % 2 == 1 or quotes.count("“") != quotes.count("”"):
            return "quoted_span"
        if not self._sentence_complete(text, split):
            window = text[max(0, split - 4200) : split]
            if any(char in ".!?" for char in window):
                return "mid_sentence"
        return None

    def is_safe(self, text: str, split: int) -> bool:
        return self.reason(text, split) is None

    def _sentence_complete(self, text: str, split: int) -> bool:
        cursor = split - 1
        while cursor >= 0 and text[cursor].isspace():
            cursor -= 1
        while cursor >= 0 and text[cursor] in "\"'”’":
            cursor -= 1
        if cursor < 0:
            return True
        return text[cursor] in ".!?;:"
