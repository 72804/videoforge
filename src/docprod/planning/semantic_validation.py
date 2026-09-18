from __future__ import annotations

from docprod.audio.script import tokenize_display
from docprod.models.enums import AssetStrategy
from docprod.planning.semantic_models import PlanWarning, SemanticSceneIntent
from docprod.research.models import ResearchDossier
from docprod.writing.models import NarrationScript

_WEATHER = ("yağmur", "kar yağıyordu", "storm", "blizzard", "thunder")
_CLOTHING = ("fedora", "red jacket", "mavi mont", "leather coat")
_VEHICLE_DETAIL = ("black chevy", "white van plate", "kırmızı kamyon plaka")
_AUTHENTIC_DOC = (
    "authentic court record",
    "scanned original indictment",
    "official court pdf facsimile",
    "gerçek mahkeme belgesi taraması",
)
_EXACT_ROUTE = ("exact route", "the truck took", "kesin güzergah", "tam güzergâh")


def named_people(dossier: ResearchDossier) -> list[str]:
    names: list[str] = []
    for item in dossier.entities:
        name = item.name.strip()
        if not name:
            continue
        role = (item.role or "").lower()
        if role in {"place", "location", "organization", "org"}:
            continue
        if any(token in name.lower() for token in ("federation", "sûreté", "surete", "reserve")):
            continue
        if " " in name or name[:1].isupper():
            names.append(name)
    return names


def disputed_figure_texts(dossier: ResearchDossier) -> list[str]:
    texts: list[str] = []
    for item in dossier.figures:
        blob = f"{item.name} {item.value_text} {item.notes}".lower()
        if any(token in blob for token in ("disagree", "range", "approximately", "or ", "–", "-")):
            texts.append(item.value_text)
    for item in dossier.uncertainties:
        texts.append(item.description)
    return texts


def hallucination_warnings(
    *,
    scene_id: str,
    intent: SemanticSceneIntent,
    strategy: AssetStrategy,
    dossier: ResearchDossier,
    script: NarrationScript,
) -> list[PlanWarning]:
    warnings: list[PlanWarning] = []
    blob = " ".join(
        [
            intent.visual_subject,
            intent.visual_action,
            intent.visual_environment,
            intent.visual_description,
            intent.image_prompt_seed,
            intent.graphic_brief,
            intent.archive_search_seed,
            intent.reasoning_summary,
        ]
    ).lower()
    people = named_people(dossier)
    invented_person = (
        intent.historical_specificity == "exact_person_or_event"
        and strategy in {AssetStrategy.ai_image, AssetStrategy.ai_image_to_video}
    )
    if invented_person:
        warnings.append(
            PlanWarning(
                code="named_person_invented_appearance",
                scene_id=scene_id,
                message=(
                    "Named/exact person or event planned as AI depiction "
                    "without archive reference."
                ),
            )
        )
    for name in people:
        if name.casefold() in blob and strategy in {
            AssetStrategy.ai_image,
            AssetStrategy.ai_image_to_video,
        }:
            warnings.append(
                PlanWarning(
                    code="named_person_invented_appearance",
                    scene_id=scene_id,
                    message=f"Named person {name!r} assigned an AI appearance.",
                )
            )
            break
    if intent.historical_specificity in {
        "exact_place_or_object",
        "exact_person_or_event",
    } and strategy in {AssetStrategy.ai_image, AssetStrategy.ai_image_to_video}:
        if not intent.source_ids and not intent.claim_ids:
            warnings.append(
                PlanWarning(
                    code="unsourced_historic_detail",
                    scene_id=scene_id,
                    message="Exact historical visual detail has no claim/source ids.",
                )
            )
    if intent.preferred_source_type == "archive" and strategy in {
        AssetStrategy.ai_image,
        AssetStrategy.ai_image_to_video,
    }:
        warnings.append(
            PlanWarning(
                code="reenactment_as_archive",
                scene_id=scene_id,
                message="Reenactment/AI visual would be presented as archive.",
            )
        )
    if any(token in blob for token in _WEATHER):
        warnings.append(
            PlanWarning(
                code="invented_weather",
                scene_id=scene_id,
                message="Precise weather/time-of-day invented for the visual.",
            )
        )
    if any(token in blob for token in _CLOTHING):
        warnings.append(
            PlanWarning(
                code="invented_clothing",
                scene_id=scene_id,
                message="Precise clothing detail invented for the visual.",
            )
        )
    if any(token in blob for token in _VEHICLE_DETAIL):
        warnings.append(
            PlanWarning(
                code="invented_object_detail",
                scene_id=scene_id,
                message="Precise vehicle/object detail invented for the visual.",
            )
        )
    if any(token in blob for token in _AUTHENTIC_DOC):
        warnings.append(
            PlanWarning(
                code="fake_authentic_document",
                scene_id=scene_id,
                message="Graphic brief implies a fake authentic court/source document.",
            )
        )
    if any(token in blob for token in _EXACT_ROUTE):
        warnings.append(
            PlanWarning(
                code="map_overprecision",
                scene_id=scene_id,
                message="Map claims more route precision than research supports.",
            )
        )
    if strategy in {AssetStrategy.generated_graphic, AssetStrategy.text_card, AssetStrategy.map}:
        if _exact_disputed_figure(intent.graphic_brief, dossier):
            warnings.append(
                PlanWarning(
                    code="disputed_figure_as_exact",
                    scene_id=scene_id,
                    message="Disputed figure rendered as an exact fact in a graphic.",
                )
            )
    known_sources = set(script_and_dossier_source_ids(dossier, script))
    unknown = [sid for sid in intent.source_ids if sid not in known_sources]
    if unknown:
        warnings.append(
            PlanWarning(
                code="unknown_source_id",
                scene_id=scene_id,
                message=f"Unknown source ids: {', '.join(unknown)}",
            )
        )
    known_claims = {item.fact_id for item in dossier.facts}
    known_claims.update(item.event_id for item in dossier.timeline_events)
    unknown_claims = [cid for cid in intent.claim_ids if cid not in known_claims]
    if unknown_claims:
        warnings.append(
            PlanWarning(
                code="unknown_claim_id",
                scene_id=scene_id,
                message=f"Unknown claim ids: {', '.join(unknown_claims)}",
            )
        )
    return _dedupe(warnings)


def script_and_dossier_source_ids(dossier: ResearchDossier, script: NarrationScript) -> set[str]:
    ids = set(dossier.source_ids_used)
    for group in (
        dossier.facts,
        dossier.timeline_events,
        dossier.figures,
        dossier.legal_outcomes,
        dossier.entities,
        dossier.locations,
    ):
        for item in group:
            ids.update(getattr(item, "source_ids", []) or [])
    for beat in script.beats:
        ids.update(beat.source_ids)
    return ids


def _exact_disputed_figure(brief: str, dossier: ResearchDossier) -> bool:
    text = brief.lower()
    if not text:
        return False
    if any(token in text for token in ("yaklaşık", "approximately", "range", "arasında", "–", "-")):
        return False
    for item in dossier.figures:
        value = item.value_text.strip()
        if len(value) < 3:
            continue
        notes = f"{item.notes} {item.value_text}".lower()
        disputed = any(token in notes for token in ("or ", "–", "-", "disagree", "range", "approx"))
        if disputed and value.lower() in text and "million" not in item.value_text.lower():
            return True
        if disputed and value.replace(",", "") in brief.replace(",", ""):
            if "18.7" in value or "18,7" in value:
                if "18" in text and "18.7" not in text and "18,7" not in text:
                    return True
            if any(ch.isdigit() for ch in value) and value in brief:
                if "or" not in text and "–" not in brief and "-" not in brief:
                    return True
    return False


def repetition_warnings(
    subjects: list[str],
    strategies: list[AssetStrategy],
    window: int = 8,
) -> list[PlanWarning]:
    warnings: list[PlanWarning] = []
    for index, subject in enumerate(subjects):
        key = _normalize_subject(subject)
        start = max(0, index - window + 1)
        recent = [_normalize_subject(item) for item in subjects[start : index + 1]]
        if key and recent.count(key) >= 3:
            warnings.append(
                PlanWarning(
                    code="subject_repetition",
                    scene_id=f"scene_{index + 1:04d}",
                    message=(
                        f"Visual subject {key!r} repeats {recent.count(key)} "
                        f"times in {window} scenes."
                    ),
                )
            )
    run = 1
    for index in range(1, len(strategies)):
        if strategies[index] == strategies[index - 1]:
            run += 1
        else:
            run = 1
        if run >= 6:
            warnings.append(
                PlanWarning(
                    code="strategy_repetition",
                    scene_id=f"scene_{index + 1:04d}",
                    message=f"{run} consecutive {strategies[index].value} scenes.",
                )
            )
    return warnings


def diversity_warnings(strategies: list[AssetStrategy]) -> list[PlanWarning]:
    warnings: list[PlanWarning] = []
    ai_run = 0
    for index, strategy in enumerate(strategies):
        if strategy in {AssetStrategy.ai_image, AssetStrategy.ai_image_to_video}:
            ai_run += 1
        else:
            ai_run = 0
        if ai_run >= 8:
            warnings.append(
                PlanWarning(
                    code="ai_still_run",
                    scene_id=f"scene_{index + 1:04d}",
                    message=f"{ai_run} consecutive AI image/video scenes.",
                )
            )
    return warnings


def _normalize_subject(text: str) -> str:
    tokens = tokenize_display(text.casefold())
    skip = {"the", "a", "an", "generic", "documentary"}
    kept = [token for token in tokens if token not in skip]
    return " ".join(kept[:3])


def _dedupe(items: list[PlanWarning]) -> list[PlanWarning]:
    seen: set[tuple[str, str, str]] = set()
    out: list[PlanWarning] = []
    for item in items:
        key = (item.code, item.scene_id, item.message)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out
