from __future__ import annotations

import hashlib
import json
from math import ceil
from typing import Any

from pydantic import BaseModel, ConfigDict

from docprod.product.enums import PlanItemType
from docprod.product.models import GenerationPlan, GenerationPlanItem, Project, SceneVersion


class PricingPolicy(BaseModel):
    """Maps provider USD estimates to customer Stars. Configurable, not a Telegram rate."""

    model_config = ConfigDict(extra="forbid")

    policy_id: str = "stars-v1"
    stars_per_provider_usd: float = 100.0
    minimum_stars: int = 1

    def stars_for_usd(self, usd: float) -> int:
        if usd <= 0:
            return 0
        return max(self.minimum_stars, int(ceil(usd * self.stars_per_provider_usd)))


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def plan_payload(
    project: Project,
    scenes: list[SceneVersion],
    items: list[GenerationPlanItem],
) -> dict[str, Any]:
    return {
        "project_id": project.id,
        "prompt": project.prompt,
        "duration_mode": project.duration_mode.value,
        "target_duration_seconds": project.target_duration_seconds,
        "aspect_ratio": project.aspect_ratio.value,
        "language": project.language,
        "quality_profile": project.quality_profile,
        "defaults": {
            "image": project.default_image_model,
            "video": project.default_video_model,
            "text": project.default_text_model,
            "voice": project.default_voice_model,
        },
        "scenes": [
            {
                "scene_id": scene.scene_id,
                "visual_prompt": scene.visual_prompt,
                "motion_prompt": scene.motion_prompt,
                "character_ids": scene.character_ids,
                "duration_seconds": scene.duration_seconds,
                "image_model": scene.image_model,
                "video_model": scene.video_model,
            }
            for scene in scenes
        ],
        "items": [item.model_dump(mode="json") for item in items],
    }


def hash_generation_plan(
    project: Project,
    scenes: list[SceneVersion],
    items: list[GenerationPlanItem],
) -> str:
    return sha256_text(canonical_json(plan_payload(project, scenes, items)))


def hash_quote(plan_hash: str, stars: int, policy_id: str) -> str:
    payload = {"plan_hash": plan_hash, "stars": stars, "policy": policy_id}
    return sha256_text(canonical_json(payload))


def default_plan_items(
    scenes: list[SceneVersion],
    *,
    animate_scene_ids: set[str] | None = None,
    policy: PricingPolicy | None = None,
) -> list[GenerationPlanItem]:
    pricing = policy or PricingPolicy()
    animate = animate_scene_ids or set()
    items: list[GenerationPlanItem] = [
        GenerationPlanItem(
            type=PlanItemType.SCRIPT,
            model="auto",
            quantity=1,
            estimated_provider_usd=0.02,
            customer_stars=pricing.stars_for_usd(0.02),
        )
    ]
    still_usd = 0.05 * len(scenes)
    items.append(
        GenerationPlanItem(
            type=PlanItemType.STILL,
            model="auto",
            quantity=len(scenes),
            estimated_provider_usd=round(still_usd, 4),
            customer_stars=pricing.stars_for_usd(still_usd),
        )
    )
    video_count = len(animate)
    video_usd = 0.40 * video_count
    if video_count:
        items.append(
            GenerationPlanItem(
                type=PlanItemType.VIDEO,
                model="veo-lite",
                quantity=video_count,
                estimated_provider_usd=round(video_usd, 4),
                customer_stars=pricing.stars_for_usd(video_usd),
                dependencies=["still"],
            )
        )
    items.append(
        GenerationPlanItem(
            type=PlanItemType.TTS,
            model="auto",
            quantity=1,
            estimated_provider_usd=0.04,
            customer_stars=pricing.stars_for_usd(0.04),
        )
    )
    items.append(
        GenerationPlanItem(
            type=PlanItemType.MUSIC,
            model="auto",
            quantity=1,
            estimated_provider_usd=0.08,
            customer_stars=pricing.stars_for_usd(0.08),
        )
    )
    items.append(
        GenerationPlanItem(
            type=PlanItemType.RENDER,
            model="ffmpeg",
            quantity=1,
            estimated_provider_usd=0.0,
            customer_stars=0,
            dependencies=["still", "tts"],
        )
    )
    return items


def assemble_plan(
    project: Project,
    scenes: list[SceneVersion],
    items: list[GenerationPlanItem],
) -> GenerationPlan:
    plan_hash = hash_generation_plan(project, scenes, items)
    usd = round(sum(item.estimated_provider_usd for item in items), 4)
    stars = sum(item.customer_stars for item in items)
    return GenerationPlan(
        project_id=project.id,
        items=items,
        plan_hash=plan_hash,
        estimated_provider_usd=usd,
        customer_stars=stars,
        scoped_scene_ids=[scene.scene_id for scene in scenes],
    )
