from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from docprod.config import Settings, get_settings
from docprod.product.engine_bridge import (
    FIRST_CANARY_PROVIDERS,
    build_engine_spec,
    persist_engine_outline,
)
from docprod.product.enums import AspectRatio, DurationMode, PlanItemType, ReferenceMode
from docprod.product.errors import ProductError
from docprod.product.limits import ProductLimits
from docprod.product.models import Character, TelegramUser
from docprod.product.persist import save_repository
from docprod.product.plans import PricingPolicy
from docprod.product.repository import MemoryRepository
from docprod.product.services import ProductService
from docprod.quality.catalog import get_model
from docprod.quality.router import estimate_model_cost
from docprod.storage.paths import default_projects_root

CANARY_SLUG = "videoforge_local_canary"
CANARY_TITLE = "Suitcase in the basement"
CANARY_PROMPT = (
    "A young man finds an old locked suitcase in the basement of his apartment "
    "building. He carries it upstairs, opens it, and discovers bundles of cash. "
    "Before he can react, someone knocks on the door."
)
CANARY_CHARACTER = "Nolan"
CANARY_HARD_CAP_USD = 2.0
CANARY_SENTINEL_TELEGRAM_ID = 900001
STAGE_B_BLOCKER = (
    "RealGenerationWorker live path remains LIVE_DISABLED until explicit Stage B "
    "enablement. Paid flags plus that gate must both be lifted together."
)


def canary_root() -> Path:
    return default_projects_root() / CANARY_SLUG


def stage_a_paths() -> dict[str, Path]:
    root = canary_root()
    return {
        "root": root,
        "store": root / "product_store.json",
        "plan": root / "artifacts" / "review" / "stage_a_plan.json",
        "report": root / "artifacts" / "review" / "stage_a_report.md",
        "final": root / "artifacts" / "render" / "final" / "documentary_preview.mp4",
    }


def _catalog_note(model_id: str) -> dict[str, Any]:
    spec = get_model(model_id)
    if spec is None:
        return {"model": model_id, "in_catalog": False, "verify_live": True}
    price = spec.pricing
    video_seconds = 8 if spec.modality.value == "video" else 0
    usd, confidence = estimate_model_cost(model_id, seconds=video_seconds)
    return {
        "model": model_id,
        "provider": spec.provider,
        "implemented": spec.implemented,
        "price_mode": price.mode.value,
        "price_value": price.value,
        "confidence": confidence.value,
        "pricing_as_of": price.pricing_as_of,
        "notes": price.notes or spec.notes,
        "verify_live": price.confidence.value in {"unresolved", "estimated"} or price.value is None,
        "catalog_estimate": usd,
    }


def build_canary_service() -> ProductService:
    repo = MemoryRepository()
    limits = ProductLimits(max_provider_usd_per_job=CANARY_HARD_CAP_USD)
    return ProductService(
        repo,
        limits=limits,
        pricing=PricingPolicy(),
        generation_mode="real",
        real_generation_canary=True,
        canary_telegram_ids=frozenset({CANARY_SENTINEL_TELEGRAM_ID}),
    )


def seed_canary_project(service: ProductService) -> tuple[str, str]:
    user = service.repo.put_user(
        TelegramUser(telegram_user_id=CANARY_SENTINEL_TELEGRAM_ID, first_name="LocalCanary")
    )
    project = service.create_project(
        user.id,
        title=CANARY_TITLE,
        prompt=CANARY_PROMPT,
        duration_mode=DurationMode.AUTO,
        aspect_ratio=AspectRatio.VERTICAL,
        quality_profile="balanced",
        language="en",
    )
    # Stable slug for local artifacts; product id remains generated.
    character = Character(
        project_id=project.id,
        name=CANARY_CHARACTER,
        description="Young man in a modest apartment building, late twenties, short dark hair.",
        locked_identity=False,
    )
    service.repo.characters[character.id] = character
    return user.id, project.id


def plan_local_canary() -> dict[str, Any]:
    """Stage A: frozen cost plan. Zero provider HTTP."""
    service = build_canary_service()
    user_id, project_id = seed_canary_project(service)
    project = service.repo.projects[project_id]
    spec = build_engine_spec(
        project,
        characters=service.repo.characters_for(project.id),
        references=[
            ref for ref in service.repo.references.values() if ref.project_id == project.id
        ],
        hard_max_usd=CANARY_HARD_CAP_USD,
        pricing=service.pricing,
    )
    if spec.estimated_provider_usd - 1e-9 > CANARY_HARD_CAP_USD:
        raise ProductError("canary estimated cost exceeds $2 hard cap")
    persist_engine_outline(service.repo, project, spec)
    stills = [item for item in spec.frozen_items if item.type is PlanItemType.STILL]
    videos = [item for item in spec.frozen_items if item.type is PlanItemType.VIDEO]
    tts = next(item for item in spec.frozen_items if item.type is PlanItemType.TTS)
    script = next(item for item in spec.frozen_items if item.type is PlanItemType.SCRIPT)
    video_seconds = sum(8 for item in videos)
    paths = stage_a_paths()
    payload: dict[str, Any] = {
        "stage": "A",
        "slug": CANARY_SLUG,
        "product_project_id": project.id,
        "title": project.title,
        "prompt": project.prompt,
        "content_kind": spec.content_kind,
        "aspect_ratio": spec.aspect_ratio,
        "quality_profile": spec.quality_profile.value,
        "duration_mode": project.duration_mode.value,
        "duration_seconds": spec.duration_seconds,
        "scene_count": spec.scene_count,
        "character": CANARY_CHARACTER,
        "reference_mode": ReferenceMode.AUTO_GENERATED.value,
        "providers": dict(FIRST_CANARY_PROVIDERS),
        "scenes": [
            {
                "order": scene.order_index + 1,
                "production_class": scene.production_class.value,
                "duration_seconds": scene.duration_seconds,
                "image_model": scene.image_model,
                "video_model": scene.video_model,
                "wants_video": scene.wants_video,
                "motion": scene.motion_prompt,
                "visual_prompt": scene.visual_prompt,
                "narration": scene.narration,
            }
            for scene in spec.scenes
        ],
        "paid_operations": [
            {
                "type": item.type.value,
                "model": item.model,
                "quantity": item.quantity,
                "estimated_provider_usd": item.estimated_provider_usd,
                "scene_id": item.scene_id,
            }
            for item in spec.frozen_items
            if item.estimated_provider_usd > 0
        ],
        "counts": {
            "text_calls": 1,
            "image_generations": len(stills),
            "video_shots": len(videos),
            "video_seconds": video_seconds,
            "tts_calls": 1,
        },
        "catalog": {
            "script": _catalog_note(script.model),
            "image": _catalog_note(
                stills[0].model if stills else FIRST_CANARY_PROVIDERS["image_model"]
            ),
            "video": _catalog_note(FIRST_CANARY_PROVIDERS["video_model"]),
            "tts": _catalog_note(tts.model),
        },
        "estimated_provider_usd": spec.estimated_provider_usd,
        "hard_cap_usd": CANARY_HARD_CAP_USD,
        "prefer_under_usd": 1.0,
        "under_prefer_budget": spec.estimated_provider_usd < 1.0 + 1e-9,
        "final_output": str(paths["final"]),
        "stage_b_blocker": STAGE_B_BLOCKER,
        "provider_http_calls": 0,
        "stars": 0,
        "user_id": user_id,
    }
    paths["root"].mkdir(parents=True, exist_ok=True)
    paths["plan"].parent.mkdir(parents=True, exist_ok=True)
    paths["final"].parent.mkdir(parents=True, exist_ok=True)
    save_repository(paths["store"], service.repo)
    paths["plan"].write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    paths["report"].write_text(_markdown_report(payload), encoding="utf-8")
    return payload


def _markdown_report(payload: dict[str, Any]) -> str:
    lines = [
        f"# Local canary Stage A — {payload['title']}",
        "",
        f"- slug: `{payload['slug']}`",
        f"- duration: {payload['duration_seconds']}s / {payload['scene_count']} scenes",
        f"- aspect: {payload['aspect_ratio']} / {payload['quality_profile']}",
        f"- estimated USD: {payload['estimated_provider_usd']}",
        f"- hard cap: {payload['hard_cap_usd']}",
        f"- final (Stage B): `{payload['final_output']}`",
        "",
        "## Scenes",
    ]
    for scene in payload["scenes"]:
        motion = "Veo Lite 8s" if scene["wants_video"] else "still + local camera"
        lines.append(
            f"- {scene['order']}. {scene['production_class']} — {motion} — {scene['image_model']}"
        )
    lines.extend(["", "## Paid operations"])
    for item in payload["paid_operations"]:
        lines.append(
            f"- {item['type']} `{item['model']}` qty={item['quantity']} "
            f"${item['estimated_provider_usd']}"
        )
    lines.extend(["", "Stage B was not executed.", ""])
    return "\n".join(lines)


def assert_canary_execute_allowed(settings: Settings | None = None) -> None:
    cfg = settings if settings is not None else get_settings()
    if cfg.generation_mode.strip().lower() != "real":
        raise ProductError("Stage B requires GENERATION_MODE=real")
    if cfg.real_generation_dry_run:
        raise ProductError("Stage B requires REAL_GENERATION_DRY_RUN=false")
    if not cfg.allow_paid_generation:
        raise ProductError("Stage B requires ALLOW_PAID_GENERATION=true")
    if not cfg.allow_paid_apis:
        raise ProductError("Stage B requires ALLOW_PAID_APIS=true")
    raise ProductError(STAGE_B_BLOCKER)


def stage_b_required_env() -> list[str]:
    return [
        "GENERATION_MODE=real",
        "REAL_GENERATION_DRY_RUN=false",
        "ALLOW_PAID_GENERATION=true",
        "ALLOW_PAID_APIS=true",
        "OPENAI_API_KEY=<local ignored .env only>",
        "GEMINI_API_KEY=<local ignored .env only, if Veo is in the frozen plan>",
        "CANARY_MAX_PROVIDER_USD=2.0",
    ]
