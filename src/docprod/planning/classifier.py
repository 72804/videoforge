from __future__ import annotations

import re
from functools import lru_cache

from docprod.planning.models import ClassificationResult, ContentCategory
from docprod.planning.rules import en, tr

# More specific categories win ties with equal score.
_PRIORITY: tuple[ContentCategory, ...] = (
    ContentCategory.document,
    ContentCategory.news,
    ContentCategory.map_or_travel,
    ContentCategory.court_or_legal,
    ContentCategory.police,
    ContentCategory.crime,
    ContentCategory.danger,
    ContentCategory.money,
    ContentCategory.phone_or_computer,
    ContentCategory.technology,
    ContentCategory.vehicle,
    ContentCategory.building,
    ContentCategory.location_establishing,
    ContentCategory.time_establishing,
    ContentCategory.crowd,
    ContentCategory.nature,
    ContentCategory.interior,
    ContentCategory.person,
    ContentCategory.action,
    ContentCategory.generic,
)
_PRIORITY_INDEX = {category: index for index, category in enumerate(_PRIORITY)}


def _language_key(language: str) -> str:
    return language.strip().lower().split("-")[0]


def _vocab(language: str) -> tuple[
    dict[ContentCategory, tuple[str, ...]],
    dict[str, int],
    tuple[str, ...],
]:
    if _language_key(language) == "tr":
        return tr.CATEGORY_TERMS, tr.MOTION_STRENGTH, tr.DOCUMENT_CONTAINER_PHRASES
    return en.CATEGORY_TERMS, en.MOTION_STRENGTH, en.DOCUMENT_CONTAINER_PHRASES


def _normalize(text: str, language: str) -> str:
    lowered = text
    if _language_key(language) == "tr":
        lowered = lowered.replace("\u0130", "i").replace("I", "ı")
    return " ".join(lowered.casefold().split())


def _term_pattern(term: str, language: str) -> re.Pattern[str]:
    normalized = _normalize(term, language)
    escaped = re.escape(normalized).replace(r"\ ", r"\s+")
    if len(normalized) >= 4:
        return re.compile(rf"(?<!\w){escaped}", re.UNICODE)
    return re.compile(rf"(?<!\w){escaped}(?!\w)", re.UNICODE)


@lru_cache(maxsize=8)
def _compiled_vocab(language_key: str) -> tuple[
    list[tuple[ContentCategory, str, re.Pattern[str]]],
    list[tuple[str, int, re.Pattern[str]]],
    list[re.Pattern[str]],
]:
    categories, motion, containers = _vocab(language_key)
    cat_patterns: list[tuple[ContentCategory, str, re.Pattern[str]]] = []
    for category, terms in categories.items():
        for term in terms:
            cat_patterns.append((category, term, _term_pattern(term, language_key)))
    motion_patterns = [
        (term, strength, _term_pattern(term, language_key))
        for term, strength in motion.items()
    ]
    container_patterns = [_term_pattern(phrase, language_key) for phrase in containers]
    return cat_patterns, motion_patterns, container_patterns


def _mask_containers(text: str, patterns: list[re.Pattern[str]]) -> str:
    masked = text
    for pattern in patterns:
        masked = pattern.sub(" ", masked)
    return " ".join(masked.split())


def classify_text(text: str, language: str) -> ClassificationResult:
    language_key = _language_key(language) or "en"
    normalized = _normalize(text, language_key)
    cat_patterns, motion_patterns, container_patterns = _compiled_vocab(language_key)
    document_haystack = _mask_containers(normalized, container_patterns)
    scores: dict[ContentCategory, int] = {}
    matched_terms: list[str] = []
    matched_categories: set[ContentCategory] = set()
    for category, term, pattern in cat_patterns:
        haystack = document_haystack if category is ContentCategory.document else normalized
        hits = pattern.findall(haystack)
        if not hits:
            continue
        scores[category] = scores.get(category, 0) + len(hits) * max(1, len(term.split()))
        matched_categories.add(category)
        if term not in matched_terms:
            matched_terms.append(term)

    motion_terms: list[str] = []
    motion_score = 0
    motion_strength = 0
    for term, strength, pattern in motion_patterns:
        hits = pattern.findall(normalized)
        if hits:
            motion_score += len(hits) * strength
            motion_strength = max(motion_strength, strength)
            if term not in motion_terms:
                motion_terms.append(term)

    if not scores:
        primary = ContentCategory.generic
        rule_score = 0
    else:
        primary = min(
            scores,
            key=lambda category: (-scores[category], _PRIORITY_INDEX[category]),
        )
        rule_score = scores[primary]

    ordered_categories = sorted(
        matched_categories,
        key=lambda category: (-scores.get(category, 0), _PRIORITY_INDEX[category]),
    )
    return ClassificationResult(
        primary_category=primary,
        matched_categories=ordered_categories,
        matched_terms=matched_terms,
        rule_score=rule_score,
        motion_terms=motion_terms,
        motion_score=motion_score,
        motion_strength=motion_strength,
    )
