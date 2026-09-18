from __future__ import annotations

import json
import re
from typing import Any

from docprod.audio.script import tokenize_display
from docprod.exceptions import ScriptValidationError
from docprod.research.models import ResearchDossier, TopicSpec
from docprod.writing.models import (
    WORDS_PER_MINUTE,
    WRITER_PROMPT_VERSION,
    NarrationBeat,
    NarrationScript,
    StoryChapter,
    StoryOutline,
)

WRITER_INSTRUCTIONS = (
    "You write a spoken Turkish documentary narration from a sourced evidence dossier.\n"
    "\nHard rules:\n"
    "- Write natural Turkish for voice-over. Do not read source IDs or citations aloud.\n"
    "- Do not invent dialogue, quotes, dates, motives, thoughts, clothing, weather, "
    "facial expressions, or unsourced physical action.\n"
    "- If the dossier does not contain a detail, omit it.\n"
    "- Prefer paraphrase. Use a direct quote only if the exact wording is in the dossier.\n"
    "- Distinguish charged / accused / convicted.\n"
    "- When figures disagree, say that sources disagree rather than picking "
    "the dramatic number.\n"
    "- Target 850-1050 Turkish words for a 6-8 minute episode.\n"
    "- Style: factual hook, conversational documentary Turkish, short/medium spoken "
    "sentences, chronology, restrained tone, no clickbait, no empty hype.\n"
    "- Structure may follow hook, setup, stored system, discovery, scale of loss, "
    "investigation, network, arrests/court, aftermath, closing — only where facts exist.\n"
    "- Return JSON only.\n"
    "\nEvery beat must include claim_ids and source_ids that exist in the dossier.\n"
)

INVENTION_PATTERNS = (
    r"\bdüşünd(?:ü|ü)\b",
    r"\bhissetti\b",
    r"\bfısıldad",
    r"\bsessizce girdi\b",
    r"\betrafına bakınd",
    r"\bkaşlarını\b",
    r"\bgülümsed",
    r"yağmur yağıyordu",
    r"kar yağıyordu",
    r"kalbi hızla",
)


def writer_json_schema() -> dict[str, Any]:
    return {
        "type": "json_schema",
        "name": "narration_script",
        "strict": False,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["outline", "beats"],
            "properties": {
                "outline": {"type": "object"},
                "beats": {"type": "array", "items": {"type": "object"}},
            },
        },
    }


def writer_input_text(topic: TopicSpec, dossier: ResearchDossier) -> str:
    body = dossier.model_dump(mode="json")
    return (
        f"PROMPT_VERSION={WRITER_PROMPT_VERSION}\n"
        f"LANGUAGE={topic.language}\n"
        f"TARGET_RUNTIME_MINUTES={topic.target_runtime_minutes}\n"
        f"CONTENT_TYPE={topic.content_type}\n"
        f"TOPIC={topic.topic}\n\n"
        "DOSSIER_JSON:\n"
        f"{json.dumps(body, ensure_ascii=False, indent=2)}\n"
    )


def parse_script_json(
    text: str,
    *,
    project_id: str,
    language: str,
    model: str,
    request_hash: str,
) -> NarrationScript:
    payload = _parse_json_object(text)
    beats_raw = payload.get("beats") or []
    beats = []
    for item in beats_raw:
        if not isinstance(item, dict):
            continue
        if "chapter" not in item:
            item["chapter"] = item.get("chapter_id") or "body"
        if "purpose" not in item:
            item["purpose"] = item.get("role") or "narration"
        if "claim_ids" not in item:
            item["claim_ids"] = item.get("fact_ids") or []
        beats.append(NarrationBeat.model_validate(item))
    outline = _coerce_outline(payload.get("outline") or {}, beats)
    full = " ".join(beat.narration.strip() for beat in beats if beat.narration.strip())
    words = tokenize_display(full)
    minutes = round(len(words) / WORDS_PER_MINUTE, 2) if words else 0.0
    return NarrationScript(
        project_id=project_id,
        language=language,
        outline=outline,
        beats=beats,
        full_narration=full,
        word_count=len(words),
        estimated_runtime_minutes=minutes,
        writer_model=model,
        request_hash=request_hash,
    )


def _coerce_outline(payload: Any, beats: list[NarrationBeat]) -> StoryOutline:
    data = dict(payload) if isinstance(payload, dict) else {}
    chapters = data.get("chapters")
    if not chapters and isinstance(data.get("structure"), list):
        built: list[dict[str, Any]] = []
        for index, item in enumerate(data["structure"], start=1):
            if isinstance(item, dict):
                title = str(item.get("title") or item.get("name") or f"Chapter {index}")
                chapter_id = str(item.get("chapter_id") or item.get("id") or f"C{index:03d}")
                purpose = str(item.get("purpose") or item.get("role") or "")
                beat_ids = item.get("beat_ids") if isinstance(item.get("beat_ids"), list) else []
            else:
                title = str(item)
                chapter_id = f"C{index:03d}"
                purpose = ""
                beat_ids = []
            built.append(
                {
                    "chapter_id": chapter_id,
                    "title": title,
                    "purpose": purpose,
                    "beat_ids": beat_ids,
                }
            )
        data["chapters"] = built
    if not data.get("logline"):
        data["logline"] = str(data.get("title") or data.get("log_line") or "")
    outline = StoryOutline.model_validate(data)
    filled: list[StoryChapter] = []
    for chapter in outline.chapters:
        ids = list(chapter.beat_ids)
        if not ids:
            ids = [
                beat.beat_id
                for beat in beats
                if beat.chapter in {chapter.chapter_id, chapter.title}
            ]
        filled.append(chapter.model_copy(update={"beat_ids": ids}))
    if (
        beats
        and filled
        and len(beats) == len(filled)
        and all(not chapter.beat_ids for chapter in filled)
    ):
        filled = [
            chapter.model_copy(update={"beat_ids": [beats[index].beat_id]})
            for index, chapter in enumerate(filled)
        ]
    return outline.model_copy(update={"chapters": filled})


def _parse_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", stripped, re.DOTALL)
    if fenced:
        stripped = fenced.group(1)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end <= start:
        raise ScriptValidationError("Writer response was not JSON")
    data = json.loads(stripped[start : end + 1])
    if not isinstance(data, dict):
        raise ScriptValidationError("Writer JSON must be an object")
    return data


def dossier_corpus(dossier: ResearchDossier) -> str:
    parts = [
        dossier.summary,
        dossier.topic,
        *[item.claim for item in dossier.facts],
        *[item.description for item in dossier.timeline_events],
        *[f"{item.name} {item.value_text} {item.notes}" for item in dossier.figures],
        *[item.description for item in dossier.legal_outcomes],
        *[item.description for item in dossier.uncertainties],
        *[item.description for item in dossier.contradictions],
        *[item.name for item in dossier.entities],
        *[item.name for item in dossier.locations],
    ]
    return "\n".join(parts).casefold()
