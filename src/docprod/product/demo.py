from __future__ import annotations

from pathlib import Path

from docprod.product.enums import (
    AssetKind,
    DurationMode,
    JobStatus,
    ReferenceMode,
)
from docprod.product.models import TelegramUser
from docprod.product.services import ProductService
from docprod.product.storage import LocalStorageBackend

DEMO_PROMPT = "Two friends find a mysterious box in their apartment."
DEMO_TELEGRAM_USER_ID = 9001


def run_telegram_product_demo(
    *,
    root: Path | None = None,
    service: ProductService | None = None,
) -> dict[str, object]:
    """Local mock fixture. No network, no Telegram Stars, no paid APIs."""
    if service is None:
        storage = LocalStorageBackend(root) if root is not None else None
        service = ProductService(storage=storage)
    user = service.repo.put_user(
        TelegramUser(
            telegram_user_id=DEMO_TELEGRAM_USER_ID,
            username=None,
            first_name="Demo",
            language_code="en",
        )
    )
    project = service.create_project(
        user.id,
        title="Mysterious box",
        prompt=DEMO_PROMPT,
        duration_mode=DurationMode.AUTO,
    )
    a = service.add_character(
        user.id,
        project.id,
        name="Lea",
        description="curious friend, apartment-casual clothes",
    )
    b = service.add_character(
        user.id,
        project.id,
        name="Noah",
        description="cautious friend, hoodie",
    )
    service.add_character_reference(user.id, a.id, b"fake-lea-ref", mode=ReferenceMode.CUSTOM)
    service.add_character_reference(user.id, b.id, b"fake-noah-ref", mode=ReferenceMode.CUSTOM)
    s1 = service.add_scene(
        user.id,
        project.id,
        visual_prompt="Two friends in a small apartment staring at a sealed box.",
        motion_prompt="subtle breathing and glance toward the box",
        character_ids=[a.id, b.id],
        duration_seconds=5,
        narration="They found the box by the door.",
    )
    s2 = service.add_scene(
        user.id,
        project.id,
        visual_prompt="Close-up of hands hovering over the mysterious box.",
        motion_prompt="fingers hesitate then pull back",
        character_ids=[a.id],
        duration_seconds=4,
        narration="Neither wanted to open it first.",
    )
    s3 = service.add_scene(
        user.id,
        project.id,
        visual_prompt="Wide shot as evening light hits the apartment.",
        motion_prompt="slow ambient motion",
        character_ids=[a.id, b.id],
        duration_seconds=6,
        narration="The room waited with them.",
    )
    plan = service.plan_project(user.id, project.id, animate_scene_ids={s1.id})
    quote = service.quote_project(user.id, project.id, plan.id)
    payment = service.confirm_telegram_payment(
        user.id,
        quote_id=quote.id,
        telegram_payment_id="demo-payment-not-sent-to-telegram",
        stars=quote.stars,
        invoice_payload=f"quote:{quote.id}",
    )
    job = service.authorize_generation(user.id, quote.id, payment.id)
    service.start_generation(user.id, job.id)
    for status in (
        JobStatus.PLANNING,
        JobStatus.GENERATING_SCRIPT,
        JobStatus.GENERATING_IMAGES,
        JobStatus.GENERATING_VIDEO,
        JobStatus.GENERATING_AUDIO,
        JobStatus.RENDERING,
    ):
        service.advance_job(job.id, status)
        if status is JobStatus.GENERATING_IMAGES:
            job.progress["images"]["completed"] = 3
            job.progress["script"]["completed"] = 1
        if status is JobStatus.GENERATING_VIDEO:
            job.progress["video"]["total"] = 1
            job.progress["video"]["completed"] = 1
        if status is JobStatus.GENERATING_AUDIO:
            job.progress["audio"]["completed"] = 1
    for scene in (s1, s2, s3):
        service.attach_mock_asset(user.id, scene.id, kind=AssetKind.IMAGE, data=b"mock-still")
    service.attach_mock_asset(user.id, s1.id, kind=AssetKind.VIDEO, data=b"mock-video")
    render = service.complete_job(job.id, storage_key="renders/demo.mp4")
    job.progress["render"]["completed"] = 1
    return {
        "user_id": user.id,
        "telegram_user_id": user.telegram_user_id,
        "project_id": project.id,
        "character_ids": [a.id, b.id],
        "scene_ids": [s1.id, s2.id, s3.id],
        "plan_id": plan.id,
        "plan_hash": plan.plan_hash,
        "quote_id": quote.id,
        "stars": quote.stars,
        "job_id": job.id,
        "render_id": render.id,
        "outbox": [n.kind for n in service.repo.outbox.values()],
        "paid_api_calls": 0,
        "telegram_network": False,
        "service": service,
    }
