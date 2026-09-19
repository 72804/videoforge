from __future__ import annotations

import html
import re

from docprod.archive.models import ArchiveReuseDecision

_TAG = re.compile(r"<[^>]+>")

PD_TOKENS = ("public domain", "publicdomain", "pd-old", "pd-us", "cc0", "cc-0", "cc zero")
BY_TOKENS = ("cc by", "cc-by", "creativecommons.org/licenses/by")
SA_TOKENS = ("by-sa", "by sa", "licenses/by-sa")
NC_ND = ("nc-nd", "by-nc", "by-nd", "noncommercial", "no derivatives", "nd ")


def strip_html(text: str) -> str:
    cleaned = _TAG.sub(" ", html.unescape(text or ""))
    return re.sub(r"\s+", " ", cleaned).strip()


def normalize_license_decision(
    *,
    license_short_name: str,
    permission: str = "",
    usage_terms: str = "",
    non_free: bool = False,
    restrictions: str = "",
    artist: str = "",
) -> tuple[ArchiveReuseDecision, str]:
    if non_free:
        return "REJECT", "NonFree metadata present"
    blob = " ".join(
        [license_short_name, permission, usage_terms, restrictions]
    ).casefold()
    if not license_short_name.strip():
        return "REVIEW_REQUIRED", "license metadata missing"
    if any(token in blob for token in ("fair use", "non-free", "nonfree", "all rights reserved")):
        return "REJECT", "clearly non-free or incompatible license"
    if any(token in blob for token in NC_ND):
        return "REJECT", "NC/ND license is incompatible with automatic reuse"
    if restrictions.strip() and "attribution" not in restrictions.casefold():
        return "REVIEW_REQUIRED", "reuse restrictions need human interpretation"
    if " or " in blob and "cc" in blob:
        return "REVIEW_REQUIRED", "ambiguous multi-license text"
    if any(token in blob for token in PD_TOKENS):
        return "AUTO_REUSABLE", "public domain or CC0"
    if any(token in blob for token in BY_TOKENS) or any(token in blob for token in SA_TOKENS):
        if not (artist or "attribution" in blob):
            return "REVIEW_REQUIRED", "CC BY family but creator metadata thin"
        return "AUTO_REUSABLE", "CC BY / CC BY-SA with attribution"
    return "REVIEW_REQUIRED", "unrecognized or incomplete license"


def attribution_text(candidate) -> str:
    parts = [
        candidate.title,
        candidate.artist or candidate.credit,
        candidate.license_short_name,
        candidate.description_url,
    ]
    return " — ".join(part for part in parts if part)
