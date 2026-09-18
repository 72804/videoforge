from __future__ import annotations

import re

from docprod.audio.script import tokenize_display
from docprod.exceptions import ScriptValidationError
from docprod.research.models import ResearchDossier
from docprod.writing.documentary import INVENTION_PATTERNS, dossier_corpus
from docprod.writing.models import (
    TARGET_WORD_MAX,
    TARGET_WORD_MIN,
    WORD_GATE_MAX,
    WORD_GATE_MIN,
    WORDS_PER_MINUTE,
    NarrationScript,
    ScriptValidationSummary,
)

_QUOTE_RE = re.compile(r"[\"“”«»]([^\"“”«»]{8,})[\"“”«»]")


def validate_script(
    script: NarrationScript,
    dossier: ResearchDossier,
    *,
    require: bool = True,
    word_min: int = WORD_GATE_MIN,
    word_max: int = WORD_GATE_MAX,
) -> tuple[NarrationScript, ScriptValidationSummary]:
    known_facts = {item.fact_id for item in dossier.facts}
    known_facts.update(event.event_id for event in dossier.timeline_events)
    known_sources = set(dossier.source_ids_used)
    for item in dossier.facts:
        known_sources.update(item.source_ids)
    for event in dossier.timeline_events:
        known_sources.update(event.source_ids)
    corpus = dossier_corpus(dossier)
    unsupported: list[str] = []
    failures: list[str] = []
    claim_ids: set[str] = set()
    source_ids: set[str] = set()
    for beat in script.beats:
        claim_ids.update(beat.claim_ids)
        source_ids.update(beat.source_ids)
        missing_claims = [cid for cid in beat.claim_ids if cid not in known_facts]
        missing_sources = [sid for sid in beat.source_ids if sid not in known_sources]
        if not beat.source_ids or missing_sources or missing_claims:
            unsupported.append(beat.beat_id)
            continue
        if _invents(beat.narration, corpus):
            unsupported.append(beat.beat_id)
    words = script.word_count or len(tokenize_display(script.full_narration))
    minutes = round(words / WORDS_PER_MINUTE, 2) if words else 0.0
    if unsupported:
        failures.append("Unsupported beats: " + ", ".join(unsupported))
    if words < word_min or words > word_max:
        failures.append(f"Word count {words} is outside {word_min}-{word_max}")
    notes: list[str] = []
    lowered = script.full_narration.casefold()
    if lowered.count("şimdi sıkı durun") or lowered.count("videoyu beğenmeyi"):
        notes.append("Clickbait cliché detected")
    summary = ScriptValidationSummary(
        passed=not failures,
        word_count=words,
        estimated_runtime_minutes=minutes,
        beat_count=len(script.beats),
        chapter_count=len(script.outline.chapters),
        claims_referenced=len(claim_ids),
        sources_referenced=len(source_ids),
        unsupported_beat_count=len(unsupported),
        unsupported_beat_ids=unsupported,
        within_target_word_range=TARGET_WORD_MIN <= words <= TARGET_WORD_MAX,
        failures=failures,
        repetition_notes=notes,
    )
    updated = script.model_copy(
        update={
            "word_count": words,
            "estimated_runtime_minutes": minutes,
            "validation": summary,
        }
    )
    if require and not summary.passed:
        raise ScriptValidationError("; ".join(failures))
    return updated, summary


def _invents(narration: str, corpus: str) -> bool:
    for pattern in INVENTION_PATTERNS:
        match = re.search(pattern, narration, flags=re.IGNORECASE)
        if match and match.group(0).casefold() not in corpus:
            return True
    for quoted in _QUOTE_RE.findall(narration):
        if quoted.strip().casefold() not in corpus and len(quoted.strip()) > 12:
            return True
    return False
