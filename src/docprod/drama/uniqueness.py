from __future__ import annotations

import re

from docprod.models.scene import Scene, ScenePlan
from docprod.storage.hashing import content_hash

COLLAGE_MARKERS = (
    "collage",
    "storyboard",
    "split-screen",
    "split screen",
    "9-image",
    "nine image",
    "contact sheet",
    "grid of photos",
    "photo grid",
    "mood board",
    "moodboard",
    "triptych",
    "multi-panel",
    "multipanel",
    "2x2",
    "3x3",
    "split image",
    "split-image",
    "fake newspaper",
    "fake UI",
    "embedded text",
)

_COLLAGE_RE = re.compile("|".join(re.escape(item) for item in COLLAGE_MARKERS), re.IGNORECASE)


def scene_visual_fingerprint(scene: Scene) -> str:
    meta = scene.metadata or {}
    prompt = (scene.generation.image_prompt or "").strip()
    path = ""
    if scene.sources:
        path = str(scene.sources[0].local_path or scene.sources[0].uri or "")
    return content_hash(
        {
            "scene_id": scene.id,
            "strategy": scene.asset_strategy.value,
            "prompt": prompt,
            "intent": scene.visual_intent.strip(),
            "title": str(meta.get("chapter_title") or ""),
            "path": path,
            "unit": str(meta.get("asset_unit_id") or ""),
        }
    )


def collage_violations(plan: ScenePlan) -> list[str]:
    hits: list[str] = []
    for scene in plan.scenes:
        hay = " ".join(
            [
                scene.visual_intent,
                scene.generation.image_prompt or "",
            ]
        )
        if _COLLAGE_RE.search(hay):
            hits.append(scene.id)
    return hits


def duplicate_fingerprints(plan: ScenePlan) -> list[tuple[str, str]]:
    seen: dict[str, str] = {}
    dupes: list[tuple[str, str]] = []
    for scene in plan.scenes:
        if scene.metadata.get("cinematic_title_card"):
            key = content_hash(
                {
                    "kind": "title",
                    "title": scene.metadata.get("chapter_title"),
                }
            )
        else:
            key = content_hash(
                {
                    "kind": "still",
                    "prompt": (scene.generation.image_prompt or "").strip(),
                    "path": (
                        str(scene.sources[0].local_path or "") if scene.sources else ""
                    ),
                }
            )
        if key in seen:
            later = scene
            if later.metadata.get("intentional_callback"):
                continue
            dupes.append((seen[key], scene.id))
        else:
            seen[key] = scene.id
    return dupes


def assert_unique_cinematic_visuals(plan: ScenePlan) -> None:
    collage = collage_violations(plan)
    if collage:
        raise ValueError(f"Collage/explainer visual policy violated: {', '.join(collage)}")
    dupes = duplicate_fingerprints(plan)
    if dupes:
        pairs = ", ".join(f"{a}=={b}" for a, b in dupes)
        raise ValueError(f"Duplicate visual identity: {pairs}")
    prompts = [
        (scene.generation.image_prompt or "").strip()
        for scene in plan.scenes
        if not scene.metadata.get("cinematic_title_card")
    ]
    if len(prompts) != len(set(prompts)):
        raise ValueError("Duplicate image prompts are not allowed")
