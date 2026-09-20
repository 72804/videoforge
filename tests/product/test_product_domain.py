from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from docprod.product.enums import (
    AssetKind,
    CustomerBillingOutcome,
    DurationMode,
    JobStatus,
    ProviderBilledStatus,
    ProviderOutcome,
    QuoteStatus,
    ReferenceMode,
)
from docprod.product.errors import (
    AuthorizationError,
    IdempotencyConflictError,
    LimitExceededError,
    OwnershipError,
    QuoteError,
)
from docprod.product.invalidation import InvalidationEvent, effects_for
from docprod.product.jobs import transition
from docprod.product.limits import ProductLimits
from docprod.product.models import TelegramUser
from docprod.product.plans import PricingPolicy, hash_generation_plan, hash_quote
from docprod.product.services import ProductService, freeze_clock
from docprod.product.settlement import classify_attempt
from docprod.product.storage import MemoryStorageBackend


def _svc(**kwargs: object) -> ProductService:
    return ProductService(**kwargs)  # type: ignore[arg-type]


def _user(svc: ProductService, tg_id: int = 7) -> TelegramUser:
    return svc.repo.put_user(TelegramUser(telegram_user_id=tg_id, first_name="T"))


def test_telegram_user_identity_is_numeric_not_username() -> None:
    svc = _svc()
    first = svc.repo.put_user(
        TelegramUser(telegram_user_id=100, username="old", first_name="A")
    )
    again = svc.repo.put_user(
        TelegramUser(telegram_user_id=100, username="new", first_name="B")
    )
    assert first.id == again.id
    assert again.username == "new"
    assert svc.repo.user_by_telegram(100) is not None


def test_project_and_character_ownership() -> None:
    svc = _svc()
    a = _user(svc, 1)
    b = _user(svc, 2)
    project = svc.create_project(a.id, title="P", prompt="a prompt")
    with pytest.raises(OwnershipError):
        svc.add_character(b.id, project.id, name="X")
    character = svc.add_character(a.id, project.id, name="X")
    with pytest.raises(OwnershipError):
        svc.add_character_reference(b.id, character.id, b"img")


def test_auto_and_fixed_duration() -> None:
    svc = _svc()
    user = _user(svc)
    auto = svc.create_project(user.id, title="A", prompt="prompt")
    assert auto.duration_mode is DurationMode.AUTO
    assert auto.target_duration_seconds is None
    fixed = svc.create_project(
        user.id,
        title="B",
        prompt="prompt",
        duration_mode=DurationMode.FIXED,
        target_duration_seconds=30,
    )
    assert fixed.target_duration_seconds == 30
    with pytest.raises(LimitExceededError):
        svc.create_project(
            user.id,
            title="C",
            prompt="prompt",
            duration_mode=DurationMode.FIXED,
            target_duration_seconds=10_000,
        )


def test_scene_and_asset_versions() -> None:
    svc = _svc()
    user = _user(svc)
    project = svc.create_project(user.id, title="P", prompt="prompt")
    scene = svc.add_scene(user.id, project.id, visual_prompt="wide shot")
    first = scene.active_version_id
    second = svc.edit_scene(user.id, scene.id, visual_prompt="tighter shot")
    assert second.id != first
    assert scene.active_version_id == second.id
    svc.restore_scene_version(user.id, scene.id, first)  # type: ignore[arg-type]
    assert scene.active_version_id == first
    asset = svc.attach_mock_asset(user.id, scene.id, kind=AssetKind.IMAGE, data=b"a")
    later = svc.attach_mock_asset(user.id, scene.id, kind=AssetKind.IMAGE, data=b"b")
    assert asset.id != later.id


def test_generation_plan_and_quote_hashing() -> None:
    svc = _svc()
    user = _user(svc)
    project = svc.create_project(user.id, title="P", prompt="prompt")
    svc.add_scene(user.id, project.id, visual_prompt="s1")
    plan = svc.plan_project(user.id, project.id)
    again = svc.plan_project(user.id, project.id)
    assert plan.plan_hash == again.plan_hash
    quote = svc.quote_project(user.id, project.id, plan.id)
    assert quote.quote_hash == hash_quote(plan.plan_hash, plan.customer_stars, "stars-v1")
    svc.edit_scene(
        user.id,
        svc.repo.scenes_for(project.id)[0].id,
        visual_prompt="changed",
    )
    with pytest.raises(QuoteError):
        svc.quote_project(user.id, project.id, plan.id)


def test_quote_expiration() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    svc = ProductService(
        limits=ProductLimits(quote_ttl_seconds=60),
        clock=freeze_clock(start),
    )
    user = _user(svc)
    project = svc.create_project(user.id, title="P", prompt="prompt")
    svc.add_scene(user.id, project.id, visual_prompt="s")
    plan = svc.plan_project(user.id, project.id)
    quote = svc.quote_project(user.id, project.id, plan.id)
    svc.clock = freeze_clock(start + timedelta(minutes=5))
    with pytest.raises(QuoteError, match="expired"):
        svc.confirm_telegram_payment(
            user.id, quote_id=quote.id, telegram_payment_id="p1", stars=quote.stars
        )


def test_payment_and_transaction_idempotency() -> None:
    svc = _svc()
    user = _user(svc)
    project = svc.create_project(user.id, title="P", prompt="prompt")
    svc.add_scene(user.id, project.id, visual_prompt="s")
    plan = svc.plan_project(user.id, project.id)
    quote = svc.quote_project(user.id, project.id, plan.id)
    a = svc.confirm_telegram_payment(
        user.id, quote_id=quote.id, telegram_payment_id="tg-pay-1", stars=quote.stars
    )
    b = svc.confirm_telegram_payment(
        user.id, quote_id=quote.id, telegram_payment_id="tg-pay-1", stars=quote.stars
    )
    assert a.id == b.id
    job_a = svc.authorize_generation(user.id, quote.id, a.id)
    job_b = svc.authorize_generation(user.id, quote.id, a.id)
    assert job_a.id == job_b.id
    assert len(svc.repo.jobs) == 1


def test_no_generation_without_authorization() -> None:
    svc = _svc()
    user = _user(svc)
    project = svc.create_project(user.id, title="P", prompt="prompt")
    svc.add_scene(user.id, project.id, visual_prompt="s")
    plan = svc.plan_project(user.id, project.id)
    quote = svc.quote_project(user.id, project.id, plan.id)
    job = svc.repo.jobs
    from docprod.product.models import GenerationJob

    rogue = GenerationJob(
        project_id=project.id,
        user_id=user.id,
        plan_hash=plan.plan_hash,
        authorized=False,
    )
    svc.repo.jobs[rogue.id] = rogue
    with pytest.raises(AuthorizationError):
        svc.start_generation(user.id, rogue.id)
    assert quote.status is QuoteStatus.OPEN
    assert len(job) == 1


def test_provider_cost_cap() -> None:
    svc = ProductService(limits=ProductLimits(max_provider_usd_per_job=0.01))
    user = _user(svc)
    project = svc.create_project(user.id, title="P", prompt="prompt")
    svc.add_scene(user.id, project.id, visual_prompt="s")
    with pytest.raises(LimitExceededError, match="provider cost cap"):
        svc.plan_project(user.id, project.id)


def test_star_transaction_conflict() -> None:
    svc = _svc()
    user = _user(svc)
    project = svc.create_project(user.id, title="P", prompt="prompt")
    svc.add_scene(user.id, project.id, visual_prompt="s")
    plan = svc.plan_project(user.id, project.id)
    quote = svc.quote_project(user.id, project.id, plan.id)
    svc.confirm_telegram_payment(
        user.id, quote_id=quote.id, telegram_payment_id="same", stars=quote.stars
    )
    from docprod.product.enums import StarTxnType
    from docprod.product.models import StarTransaction

    with pytest.raises(IdempotencyConflictError):
        svc.repo.put_transaction(
            StarTransaction(
                user_id=user.id,
                type=StarTxnType.PURCHASE,
                telegram_payment_id="same",
                stars=quote.stars + 5,
                idempotency_key="payment:same",
            )
        )


def test_generation_state_machine() -> None:
    with pytest.raises(Exception):
        transition(JobStatus.COMPLETED, JobStatus.QUEUED)
    assert transition(JobStatus.WAITING_FOR_PAYMENT, JobStatus.QUEUED) is JobStatus.QUEUED


def test_empty_result_and_refund_representation() -> None:
    empty_billed = classify_attempt(
        outcome=ProviderOutcome.EMPTY_RESULT, billed=ProviderBilledStatus.BILLED
    )
    assert empty_billed.customer_billing is CustomerBillingOutcome.POLICY_PENDING
    failed_free = classify_attempt(
        outcome=ProviderOutcome.FAILED, billed=ProviderBilledStatus.NOT_BILLED
    )
    assert failed_free.customer_billing is CustomerBillingOutcome.REFUND_ELIGIBLE


def test_dependency_invalidation_and_local_regen() -> None:
    motion = effects_for(InvalidationEvent.SCENE_MOTION_PROMPT_CHANGED)
    assert motion["image"] is False
    assert motion["video"] is True
    order = effects_for(InvalidationEvent.SCENE_REORDERED)
    assert order["image"] is False and order["video"] is False and order["render"] is True
    svc = _svc()
    user = _user(svc)
    project = svc.create_project(user.id, title="P", prompt="prompt")
    s1 = svc.add_scene(user.id, project.id, visual_prompt="one")
    s2 = svc.add_scene(user.id, project.id, visual_prompt="two")
    v2_before = svc.repo.scene_versions[s2.active_version_id]  # type: ignore[index]
    svc.regenerate_scene_image(user.id, s1.id)
    v2_after = svc.repo.scene_versions[s2.active_version_id]  # type: ignore[index]
    assert v2_before.id == v2_after.id
    svc.regenerate_scene_video(user.id, s1.id)
    assert svc.repo.scene_versions[s1.active_version_id].video_stale  # type: ignore[index]
    assert svc.repo.scene_versions[s1.active_version_id].image_stale is False  # type: ignore[index]


def test_storage_abstraction(tmp_path) -> None:
    from docprod.product.storage import LocalStorageBackend

    local = LocalStorageBackend(tmp_path)
    local.put_bytes("a/b.bin", b"hi", content_type="text/plain")
    assert local.get_bytes("a/b.bin") == b"hi"
    mem = MemoryStorageBackend()
    mem.put_bytes("k", b"x")
    assert mem.exists("k")


def test_notification_outbox_and_limits() -> None:
    svc = ProductService(limits=ProductLimits(max_characters_per_project=1))
    user = _user(svc)
    project = svc.create_project(user.id, title="P", prompt="prompt")
    svc.add_character(user.id, project.id, name="A")
    with pytest.raises(LimitExceededError):
        svc.add_character(user.id, project.id, name="B")
    svc.add_scene(user.id, project.id, visual_prompt="s")
    plan = svc.plan_project(user.id, project.id)
    quote = svc.quote_project(user.id, project.id, plan.id)
    payment = svc.confirm_telegram_payment(
        user.id, quote_id=quote.id, telegram_payment_id="p", stars=quote.stars
    )
    job = svc.authorize_generation(user.id, quote.id, payment.id)
    svc.start_generation(user.id, job.id)
    for status in (
        JobStatus.PLANNING,
        JobStatus.GENERATING_SCRIPT,
        JobStatus.GENERATING_IMAGES,
        JobStatus.GENERATING_VIDEO,
        JobStatus.GENERATING_AUDIO,
        JobStatus.RENDERING,
    ):
        svc.advance_job(job.id, status)
    svc.complete_job(job.id, storage_key="r.mp4")
    kinds = [n.kind for n in svc.repo.outbox.values()]
    assert "project_ready" in kinds


def test_reference_modes_reuse_engine() -> None:
    assert ReferenceMode.CUSTOM.value == "CUSTOM"
    assert ReferenceMode.AUTO_GENERATED.value == "AUTO_GENERATED"
    assert ReferenceMode.HYBRID.value == "HYBRID"


def test_pricing_policy_is_configurable() -> None:
    cheap = PricingPolicy(stars_per_provider_usd=10, minimum_stars=1)
    assert cheap.stars_for_usd(0.40) == 4
    rich = PricingPolicy(stars_per_provider_usd=200, minimum_stars=1)
    assert rich.stars_for_usd(0.40) == 80


def test_plan_hash_changes_with_prompt() -> None:
    svc = _svc()
    user = _user(svc)
    project = svc.create_project(user.id, title="P", prompt="one")
    svc.add_scene(user.id, project.id, visual_prompt="s")
    a = svc.plan_project(user.id, project.id)
    svc.update_project(user.id, project.id, prompt="two")
    b = svc.plan_project(user.id, project.id)
    assert a.plan_hash != b.plan_hash
    versions = svc.repo.active_versions(project.id)
    assert hash_generation_plan(svc.repo.projects[project.id], versions, b.items) == b.plan_hash
