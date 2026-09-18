from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field

from docprod.models.enums import AssetStrategy
from docprod.models.scene import Scene, ScenePlan

_WORD_RE = re.compile(r"[\wğüşöçıİĞÜŞÖÇ]+", re.UNICODE | re.IGNORECASE)
_EXCLUSIVE_CAST = (
    "polis memur",
    "polisler",
    "memurlar",
)
_CROWD_TERMS = ("kalabalık", "crowd")
_OBJECT_CATEGORIES = frozenset(
    {
        "money",
        "document",
        "map",
        "map_or_travel",
        "location_establishing",
        "generated_graphic",
        "news",
    }
)


class CharacterReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    cue_terms: list[str]
    description: str


class VisualBible(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    project_id: str
    characters: list[CharacterReference] = Field(default_factory=list)

    @property
    def protagonist_description(self) -> str | None:
        if not self.characters:
            return None
        return self.characters[0].description

    @property
    def cue_terms(self) -> tuple[str, ...]:
        terms: list[str] = []
        for character in self.characters:
            terms.extend(character.cue_terms)
        return tuple(terms)


def _tokens(text: str) -> list[str]:
    return [token.lower() for token in _WORD_RE.findall(text)]


def _scene_text(scene: Scene) -> str:
    return f"{scene.narration} {scene.visual_intent}"


def _has_exclusive_other_cast(text: str) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in _EXCLUSIVE_CAST)


def _has_crowd(text: str) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in _CROWD_TERMS)


def _has_cue(text: str, terms: tuple[str, ...] | list[str]) -> bool:
    lowered = text.lower()
    tokens = set(_tokens(text))
    for term in terms:
        needle = term.lower().strip()
        if not needle:
            continue
        if " " in needle:
            if needle in lowered:
                return True
        elif needle in tokens:
            return True
    return False


def primary_visual_category(scene: Scene) -> str:
    return str(scene.metadata.get("primary_category") or "").lower()


def scene_includes_protagonist(
    scene: Scene,
    bible: VisualBible | None,
    *,
    previous_had_protagonist: bool = False,
) -> bool:
    if bible is None or not bible.cue_terms:
        return False
    if scene.asset_strategy not in {
        AssetStrategy.ai_image,
        AssetStrategy.ai_image_to_video,
    }:
        return False
    category = primary_visual_category(scene)
    text = _scene_text(scene)
    if _has_cue(text, bible.cue_terms):
        return True
    if category in _OBJECT_CATEGORIES:
        return False
    if _has_exclusive_other_cast(text):
        return False
    words = _tokens(scene.narration)
    if len(words) <= 2 and previous_had_protagonist:
        return True
    reason = str(scene.metadata.get("segmentation_reason") or "")
    if "visual_bridge" in reason and previous_had_protagonist:
        return True
    object_only = any(
        term in text.lower()
        for term in ("evrak çantası", "tomar para", "haber kupürü", "haritada")
    )
    if object_only:
        return False
    if previous_had_protagonist:
        return True
    return False


def scene_contains_protagonist(
    scene: Scene,
    bible: VisualBible | None,
    *,
    previous_had_protagonist: bool = False,
) -> bool:
    """Independent of primary_visual_category: crowd/police may still include him."""
    return scene_includes_protagonist(
        scene, bible, previous_had_protagonist=previous_had_protagonist
    )


def next_protagonist_memory(
    scene: Scene,
    bible: VisualBible | None,
    previous_had_protagonist: bool,
) -> tuple[bool, bool]:
    include = scene_includes_protagonist(
        scene, bible, previous_had_protagonist=previous_had_protagonist
    )
    if include:
        return include, True
    if _has_exclusive_other_cast(_scene_text(scene)):
        return include, False
    return include, previous_had_protagonist


def derive_visual_bible(plan: ScenePlan) -> VisualBible:
    """Generic recurring protagonist from narration that actually mentions him."""
    combined = " ".join(f"{scene.narration} {scene.visual_intent}" for scene in plan.scenes)
    lowered = combined.lower()
    cue_terms: list[str] = []
    bits: list[str] = []
    if re.search(r"\badam\b", lowered):
        cue_terms.append("adam")
        bits.append("the same adult man across reenactment scenes")
    if "koyu palto" in lowered or "paltolu" in lowered:
        cue_terms.append("paltolu")
        cue_terms.append("koyu palto")
        bits.append("dark practical coat")
    if not cue_terms:
        return VisualBible(project_id=plan.project_id, characters=[])
    bits.extend(
        [
            "ordinary contemporary appearance",
            "face not always clearly visible",
        ]
    )
    return VisualBible(
        project_id=plan.project_id,
        characters=[
            CharacterReference(
                id="protagonist",
                cue_terms=sorted(set(cue_terms)),
                description=", ".join(bits),
            )
        ],
    )
