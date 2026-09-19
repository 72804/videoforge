from __future__ import annotations

from docprod.models.enums import AssetStrategy
from docprod.models.scene import Scene
from docprod.planning.planner import motion_prompt_for
from docprod.production.balance import NAMED

NEGATIVE = [
    "named historical portrait",
    "recognizable real person likeness",
    "fake readable court document",
    "invented logos",
    "NYPD",
    "modern smartphone close-up unless sourced",
    "cinematic color grade buzzwords",
    "exact unsourced truck route",
]


def still_prompt_for(scene: Scene) -> str:
    subject = str(scene.metadata.get("visual_subject") or scene.visual_intent)
    action = str(scene.metadata.get("visual_action") or "")
    env = str(scene.metadata.get("visual_environment") or "")
    seed = str(scene.metadata.get("image_prompt_seed") or "")
    period = "Quebec, circa 2011-2012"
    body = ". ".join(part for part in (seed, subject, action, env, period) if part.strip())
    body += (
        ". Documentary still photograph, naturalistic lighting, 16:9, anonymous figures, "
        "no readable forged documents, no named-person likeness."
    )
    return body


def video_motion_for(scene: Scene) -> str:
    subject = str(scene.metadata.get("visual_subject") or scene.visual_intent)
    action = str(scene.metadata.get("visual_action") or scene.narration)
    base = motion_prompt_for(action, [])
    return (
        f"{subject}: {action}. {base}. Anonymous workers only; no named-person likeness."
    )


def historical_constraints(scene: Scene) -> list[str]:
    constraints = [
        "Do not invent named-person appearance",
        "Do not present reenactment as archival fact",
        "Approximate period only: 2011-2012 Quebec industrial/rural",
    ]
    if any(name in _blob(scene) for name in NAMED):
        constraints.append("Named historical person: do not generate a likeness")
    return constraints


def _blob(scene: Scene) -> str:
    return (
        f"{scene.narration} {scene.visual_intent} "
        f"{scene.metadata.get('visual_subject')}"
    ).casefold()


def fallback_strategy(scene: Scene) -> AssetStrategy:
    text = _blob(scene)
    if any(name in text for name in NAMED):
        return AssetStrategy.archive_image
    if scene.asset_strategy in {AssetStrategy.archive_image, AssetStrategy.archive_video}:
        return AssetStrategy.stock_video
    if scene.asset_strategy is AssetStrategy.stock_video:
        return AssetStrategy.ai_image
    if scene.asset_strategy in {
        AssetStrategy.generated_graphic,
        AssetStrategy.document,
        AssetStrategy.map,
        AssetStrategy.text_card,
    }:
        return AssetStrategy.stock_video
    return scene.asset_strategy
