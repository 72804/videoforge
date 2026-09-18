from __future__ import annotations

from docprod.models.enums import Mood
from docprod.models.scene import Scene

DOCUMENTARY_STYLE = (
    "photorealistic cinematic documentary reenactment, naturalistic lighting, "
    "credible real-world environment, subtle filmic contrast, 35mm documentary "
    "photography, restrained composition, realistic anatomy, realistic materials, "
    "no visible text, no watermark, 16:9"
)

AVOIDANCE = (
    "Avoid text, watermarks, logos, distorted anatomy, duplicated people, extra "
    "fingers, surreal objects, illustration or cartoon look, glossy advertising, "
    "oversaturated color, fantasy spectacle, and gratuitous gore."
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


def build_documentary_image_prompt(scene: Scene) -> str:
    """Preserve scene facts and apply a consistent documentary visual language."""
    facts = " ".join(
        part.strip()
        for part in (
            scene.visual_intent,
            scene.generation.image_prompt or "",
            scene.narration,
        )
        if part and part.strip()
    )
    category = str(scene.metadata.get("primary_category") or "").replace("_", " ")
    mood_line = ""
    category_l = category.lower()
    if scene.mood in _MOODY or "crime" in category_l or "myster" in category_l:
        mood_line = (
            "Moody practical lighting, subtle shadows, realistic documentary framing. "
            "Do not crush blacks or make the frame unnaturally dark."
        )
    category_line = f"Subject category: {category}." if category else ""
    constraint = (
        "Depict only facts stated in the narration and visual intent. "
        "Preserve exact counts, objects, and places. Do not invent names, ages, "
        "brands, clothing, or identity details that are not specified."
    )
    parts = [
        facts,
        constraint,
        category_line,
        mood_line,
        DOCUMENTARY_STYLE,
        AVOIDANCE,
    ]
    return " ".join(part.strip() for part in parts if part and part.strip())
