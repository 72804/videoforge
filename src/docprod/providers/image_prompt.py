from __future__ import annotations

import re
from collections.abc import Iterable

from docprod.models.enums import Mood, VisualEffect
from docprod.models.scene import Scene
from docprod.planning.visual_bible import VisualBible, scene_includes_protagonist

DOCUMENTARY_STYLE = (
    "photorealistic cinematic documentary reenactment, credible real-world environment, "
    "naturalistic practical lighting, subtle filmic contrast, 35mm documentary photography, "
    "restrained composition, realistic materials, 16:9"
)

CONSTRAINTS = (
    "Depict only facts supported by the narration and visual intent. "
    "Preserve exact counts, objects, and places. Do not invent names, ages, brands, "
    "clothing, or identity details that are not specified. No visible text, logos, or "
    "watermarks. Avoid illustration, cartoon look, surrealism, distorted anatomy, "
    "duplicated people, extra fingers, oversaturated advertising imagery, fantasy "
    "spectacle, and gratuitous gore. Render one single continuous photographic frame; "
    "avoid split screen, collage, contact sheet, storyboard, multiple panels, "
    "before-and-after layout, or a sequence of frames."
)

SINGLE_FRAME = "one single continuous photographic frame"

THIN_FACT_TOKEN_LIMIT = 4

COMPOSITION = (
    "Compose with modest surrounding environment and safe framing for a subtle "
    "documentary camera push or pan, without oversized empty borders."
)

PROTAGONIST_FRAMING = (
    "Keep this the same recurring adult man when he appears. Prefer rear view, side "
    "profile, or medium/wide candid documentary framing rather than a centered portrait. "
    "The face need not be clearly visible."
)

_BOILERPLATE_PREFIXES = (
    "documentary visual representing:",
    "documentary portrait representing:",
    "documentary reenactment of the described action:",
    "documentary visual of money or value representing:",
    "documentary visual related to police activity:",
    "documentary map or travel graphic representing:",
    "documentary close-up of a document or record representing:",
    "establishing documentary shot representing:",
    "documentary visual of",
)

_STYLE_NOISE = frozenset(
    {
        "16",
        "9",
        "35mm",
        "cinematic",
        "documentary",
        "look",
        "natural",
        "lighting",
        "photorealistic",
        "photography",
        "realistic",
        "reenactment",
        "representing",
    }
)

_DETAIL_CATEGORIES = frozenset({"money", "document", "news", "map", "generated_graphic"})
_DETAIL_EFFECTS = frozenset(
    {
        VisualEffect.photo_table,
        VisualEffect.evidence_board,
        VisualEffect.newspaper_reveal,
        VisualEffect.circle_highlight,
    }
)
_MOODY = frozenset(
    {
        Mood.tense,
        Mood.ominous,
        Mood.mysterious,
        Mood.urgent,
        Mood.chaotic,
    }
)
_TOKEN_RE = re.compile(r"[\wğüşöçıİĞÜŞÖÇ]+", re.UNICODE)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _tokens(text: str) -> set[str]:
    return {token.lower() for token in _TOKEN_RE.findall(text)}


def token_overlap_ratio(left: str, right: str) -> float:
    a, b = _tokens(left), _tokens(right)
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def _is_redundant(candidate: str, kept: Iterable[str]) -> bool:
    cand_n = _normalize(candidate)
    if not cand_n:
        return True
    for item in kept:
        kept_n = _normalize(item)
        if cand_n == kept_n or cand_n in kept_n or kept_n in cand_n:
            return True
        if token_overlap_ratio(candidate, item) >= 0.82:
            return True
    return False


def strip_boilerplate(text: str) -> str:
    current = text.strip()
    changed = True
    while changed and current:
        changed = False
        lowered = current.lower()
        for prefix in _BOILERPLATE_PREFIXES:
            if lowered.startswith(prefix):
                current = current[len(prefix) :].strip(" :,-")
                changed = True
                break
    return current.strip()


def _drop_style_noise(text: str) -> str:
    kept = [token for token in _TOKEN_RE.findall(text) if token.lower() not in _STYLE_NOISE]
    if len(kept) < 3:
        return ""
    return text.strip()


def _split_chunks(text: str) -> list[str]:
    raw = strip_boilerplate(text)
    if not raw:
        return []
    parts = re.split(r"(?<=[.!?])\s+|\n+|;\s*", raw)
    chunks: list[str] = []
    for part in parts:
        cleaned = part.strip(" ,;-")
        if cleaned:
            chunks.append(cleaned)
    return chunks or ([raw] if raw else [])


def collect_unique_scene_facts(scene: Scene) -> list[str]:
    """Keep narration plus unique visual/planner facts; drop duplicated boilerplate."""
    ordered: list[str] = []
    for source, strip_style in (
        (scene.narration, False),
        (scene.visual_intent, False),
        (scene.generation.image_prompt or "", True),
    ):
        if not source or not source.strip():
            continue
        for chunk in _split_chunks(source):
            candidate = _drop_style_noise(chunk) if strip_style else chunk
            if not candidate:
                continue
            if _is_redundant(candidate, ordered):
                continue
            ordered.append(candidate)
    return ordered


def is_semantically_thin(scene: Scene) -> bool:
    """Judge thinness from narration/visual intent, not leftover planner boilerplate."""
    text = f"{strip_boilerplate(scene.narration)} {strip_boilerplate(scene.visual_intent)}"
    return len(_tokens(text)) < THIN_FACT_TOKEN_LIMIT


def neighbor_context_snippets(
    scene: Scene,
    *,
    previous_scene: Scene | None = None,
    next_scene: Scene | None = None,
) -> list[str]:
    """Adjacent narration as context only; never duplicate the current beat."""
    current_facts = collect_unique_scene_facts(scene)
    snippets: list[str] = []
    for neighbor in (previous_scene, next_scene):
        if neighbor is None or not neighbor.narration.strip():
            continue
        candidate = strip_boilerplate(neighbor.narration)
        if not candidate:
            continue
        if _is_redundant(candidate, [*current_facts, *snippets]):
            continue
        snippets.append(candidate)
    return snippets


def scene_neighbors(plan_scenes: list[Scene], scene_id: str) -> tuple[Scene | None, Scene | None]:
    index = next((i for i, item in enumerate(plan_scenes) if item.id == scene_id), None)
    if index is None:
        return None, None
    previous_scene = plan_scenes[index - 1] if index > 0 else None
    next_scene = plan_scenes[index + 1] if index + 1 < len(plan_scenes) else None
    return previous_scene, next_scene


def _is_detail_scene(scene: Scene) -> bool:
    category = str(scene.metadata.get("primary_category") or "").lower()
    if category in _DETAIL_CATEGORIES:
        return True
    return scene.effect in _DETAIL_EFFECTS


def build_documentary_image_prompt(
    scene: Scene,
    *,
    bible: VisualBible | None = None,
    include_protagonist: bool | None = None,
    previous_scene: Scene | None = None,
    next_scene: Scene | None = None,
) -> str:
    """One concise scene description plus a single documentary style block."""
    facts = collect_unique_scene_facts(scene)
    description = " ".join(facts) if facts else strip_boilerplate(scene.visual_intent)
    parts: list[str] = []
    if is_semantically_thin(scene):
        context = neighbor_context_snippets(
            scene, previous_scene=previous_scene, next_scene=next_scene
        )
        if context:
            parts.append(
                "Single continuous documentary frame. "
                f"Context: {' '.join(context)} "
                f"Current visual moment: {description} "
                "Depict only the current moment."
            )
        else:
            parts.append(description)
    else:
        parts.append(description)
    if include_protagonist is None:
        include_protagonist = scene_includes_protagonist(scene, bible)
    if include_protagonist and bible and bible.protagonist_description:
        parts.append(bible.protagonist_description.rstrip(".") + ".")
        parts.append(PROTAGONIST_FRAMING)
    if not _is_detail_scene(scene):
        parts.append(COMPOSITION)
    category = str(scene.metadata.get("primary_category") or "").replace("_", " ")
    category_l = category.lower()
    if scene.mood in _MOODY or "crime" in category_l or "myster" in category_l:
        parts.append(
            "Use moody practical lighting and subtle shadows with realistic documentary "
            "framing, without crushing blacks or making the frame unnaturally dark."
        )
    parts.append(DOCUMENTARY_STYLE)
    parts.append(CONSTRAINTS)
    if scene.generation.negative_prompt:
        parts.append(f"Also avoid: {scene.generation.negative_prompt.strip()}.")
    return " ".join(part.strip() for part in parts if part and part.strip())
