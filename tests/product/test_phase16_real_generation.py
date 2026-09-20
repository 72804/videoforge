from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from docprod.api.app import create_app
from docprod.api.session import SessionIssuer
from docprod.config import Settings, validate_runtime_settings
from docprod.product.canary import canary_allows, parse_telegram_allowlist
from docprod.product.durable import DurableGenerationWorker
from docprod.product.engine_bridge import build_engine_spec, canary_duration, map_character_set
from docprod.product.enums import (
    AttemptStatus,
    DurationMode,
    JobStatus,
    PlanItemType,
    ProviderBilledStatus,
    ProviderOutcome,
)
from docprod.product.errors import LimitExceededError
from docprod.product.limits import ProductLimits
from docprod.product.models import GenerationJob, TelegramUser
from docprod.product.paid_ops import (
    CostCapExceeded,
    accounted_usd,
    assert_within_cap,
    existing_paid_attempt,
    must_not_resubmit,
    recover_submitted_without_resubmit,
    request_fingerprint,
)
from docprod.product.real_worker import LIVE_DISABLED, RealGenerationWorker
from docprod.product.s3_storage import FakeS3Storage, S3CompatibleStorage
from docprod.product.services import ProductService
from docprod.quality.enums import QualityProfile, SceneProductionClass


def _prod(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_env": "production",
        "payment_mode": "telegram",
        "generation_mode": "mock",
        "allow_paid_generation": False,
        "allow_paid_apis": False,
        "product_persistence": "postgres",
        "database_url": "postgresql://u:p@localhost/db",
        "telegram_bot_token": "placeholder-token",
        "telegram_mini_app_url": "https://app.example",
        "api_session_secret": "session-secret",
        "telegram_webhook_secret": "webhook-secret",
        "internal_job_secret": "internal-job-secret",
        "api_cors_origins": "https://app.example",
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


def _job(svc: ProductService, *, tg_id: int = 9) -> tuple[TelegramUser, GenerationJob]:
    user = svc.repo.put_user(TelegramUser(telegram_user_id=tg_id, first_name="Canary"))
    project = svc.create_project(user.id, title="Forge", prompt="Two friends find a key")
    plan = svc.plan_project(user.id, project.id)
    quote = svc.quote_project(user.id, project.id, plan.id)
    payment = svc.confirm_telegram_payment(
        user.id, quote_id=quote.id, telegram_payment_id=f"pay-{tg_id}", stars=quote.stars
    )
    job = svc.authorize_generation(user.id, quote.id, payment.id)
    return user, job


def test_api_rejects_real_generation_mode() -> None:
    try:
        validate_runtime_settings(_prod(generation_mode="real"), role="api")
    except RuntimeError as exc:
        assert "worker-only" in str(exc)
    else:
        raise AssertionError("expected failure")


def test_api_rejects_provider_keys() -> None:
    try:
        validate_runtime_settings(_prod(openai_api_key="sk-test"), role="api")
    except RuntimeError as exc:
        assert "OPENAI_API_KEY" in str(exc)
    else:
        raise AssertionError("expected failure")


def test_worker_real_dry_run_without_paid_flags() -> None:
    validate_runtime_settings(
        _prod(
            generation_mode="real",
            real_generation_dry_run=True,
            api_session_secret=None,
            telegram_webhook_secret=None,
        ),
        role="worker",
    )


def test_worker_live_requires_both_paid_flags() -> None:
    try:
        validate_runtime_settings(
            _prod(
                generation_mode="real",
                real_generation_dry_run=False,
                allow_paid_generation=True,
                allow_paid_apis=False,
            ),
            role="worker",
        )
    except RuntimeError as exc:
        assert "ALLOW_PAID" in str(exc)
    else:
        raise AssertionError("expected failure")


def test_canary_allowlist_not_hardcoded() -> None:
    allow = parse_telegram_allowlist("11, 22")
    assert canary_allows(11, allow, required=True)
    assert not canary_allows(99, allow, required=True)
    assert canary_allows(99, allow, required=False)


def test_canary_blocks_unauthorized_user() -> None:
    svc = ProductService(real_generation_canary=True, canary_telegram_ids=frozenset({11}))
    user = svc.repo.put_user(TelegramUser(telegram_user_id=99, first_name="Nope"))
    project = svc.create_project(user.id, title="P", prompt="prompt")
    plan = svc.plan_project(user.id, project.id)
    quote = svc.quote_project(user.id, project.id, plan.id)
    payment = svc.confirm_telegram_payment(
        user.id, quote_id=quote.id, telegram_payment_id="x", stars=quote.stars
    )
    with pytest.raises(LimitExceededError):
        svc.authorize_generation(user.id, quote.id, payment.id)


def test_auto_and_fixed_canary_duration() -> None:
    svc = ProductService(generation_mode="real")
    user = svc.repo.put_user(TelegramUser(telegram_user_id=1, first_name="A"))
    auto = svc.create_project(user.id, title="A", prompt="prompt")
    seconds, scenes = canary_duration(auto)
    assert seconds == 24
    assert scenes == 3
    fixed = svc.create_project(
        user.id,
        title="B",
        prompt="prompt",
        duration_mode=DurationMode.FIXED,
        target_duration_seconds=30,
    )
    seconds, scenes = canary_duration(fixed)
    assert 15 <= seconds <= 30
    assert 2 <= scenes <= 5


def test_character_refs_lock_and_map_to_engine() -> None:
    svc = ProductService(generation_mode="real")
    user = svc.repo.put_user(TelegramUser(telegram_user_id=1, first_name="A"))
    project = svc.create_project(user.id, title="P", prompt="friends talk")
    character = svc.add_character(user.id, project.id, name="Lea")
    svc.update_character(user.id, character.id, locked_identity=True)
    svc.add_character_reference(user.id, character.id, b"ref-bytes")
    mapped = map_character_set(
        project,
        svc.repo.characters_for(project.id),
        list(svc.repo.references.values()),
    )
    profile = mapped.profiles[0]
    assert profile.locked
    assert profile.custom_references
    assert profile.primary_reference


def test_engine_spec_freezes_plan_and_limits_video() -> None:
    svc = ProductService(generation_mode="real")
    _user, job = _job(svc)
    project = svc.repo.projects[job.project_id]
    spec = build_engine_spec(
        project,
        characters=svc.repo.characters_for(project.id),
        references=[],
        hard_max_usd=2.0,
        pricing=svc.pricing,
    )
    assert spec.content_kind == "custom_story"
    assert spec.quality_profile is QualityProfile.BALANCED
    assert spec.scene_count == 3
    assert sum(1 for scene in spec.scenes if scene.wants_video) <= 1
    assert spec.estimated_provider_usd <= spec.hard_max_usd
    static = [s for s in spec.scenes if s.production_class is SceneProductionClass.STATIC_CINEMATIC]
    assert static
    assert all(not row.wants_video for row in static)


def test_cost_cap_stops_before_provider() -> None:
    job = GenerationJob(
        project_id="p",
        user_id="u",
        plan_hash="h",
        provider_cost_cap=0.1,
        estimated_provider_cost=0.5,
    )
    with pytest.raises(CostCapExceeded):
        assert_within_cap(job, 0.2, spent=0.0)


def test_dry_run_worker_completes_without_paid_calls() -> None:
    svc = ProductService(generation_mode="real", storage=FakeS3Storage())
    user, job = _job(svc)
    worker = RealGenerationWorker(svc, dry_run=True)
    worker.run_job(job.id)
    stored = svc.repo.jobs[job.id]
    assert stored.status is JobStatus.COMPLETED
    assert worker.paid_calls == 0
    assert stored.progress["final_asset_version_id"]
    assert svc.storage.exists(next(iter(svc.repo.renders.values())).storage_key)
    notes = [n for n in svc.repo.outbox.values() if n.job_id == job.id]
    assert notes and "ready" in notes[0].payload["text"].lower()
    units = {u["label"] for u in svc.get_job_status(user.id, job.id).units}
    assert {"story", "images", "render", "upload"} <= units


def test_paid_fingerprint_prevents_duplicate_submit() -> None:
    svc = ProductService(generation_mode="real")
    _user, job = _job(svc)
    fingerprint = request_fingerprint(
        provider="google",
        model="veo-3.1-lite-generate-preview",
        item_type=PlanItemType.VIDEO,
        scene_id="s1",
        extra={"duration": 8},
    )
    first = svc.record_attempt(
        job.id,
        item_type=PlanItemType.VIDEO,
        provider="google",
        model="veo-3.1-lite-generate-preview",
        outcome=ProviderOutcome.SUCCEEDED,
        billed=ProviderBilledStatus.UNKNOWN,
        status=AttemptStatus.SUBMITTED,
        request_hash=fingerprint,
        remote_operation_id="op-1",
        estimated_provider_cost=0.4,
        scene_id="s1",
    )
    assert must_not_resubmit(first)
    recovered = recover_submitted_without_resubmit(svc, job.id)
    assert recovered[0].id == first.id
    assert recovered[0].status is AttemptStatus.RECOVERING_REMOTE
    again = existing_paid_attempt(svc.repo, job.id, fingerprint)
    assert again is not None
    assert again.remote_operation_id == "op-1"


def test_live_path_is_gated() -> None:
    svc = ProductService(generation_mode="real")
    _user, job = _job(svc)
    worker = RealGenerationWorker(
        svc,
        dry_run=False,
        allow_paid_generation=True,
        allow_paid_apis=True,
    )
    worker.run_job(job.id)
    assert svc.repo.jobs[job.id].status is JobStatus.FAILED
    assert worker.paid_calls == 0
    assert LIVE_DISABLED


def test_scene_regeneration_does_not_rebuild_others() -> None:
    svc = ProductService(generation_mode="real", storage=FakeS3Storage())
    user, job = _job(svc)
    RealGenerationWorker(svc, dry_run=True).run_job(job.id)
    scenes = svc.repo.scenes_for(job.project_id)
    keep = {scene.id: scene.active_version_id for scene in scenes}
    target = scenes[0]
    job2 = GenerationJob(
        project_id=job.project_id,
        user_id=user.id,
        plan_hash=job.plan_hash,
        status=JobStatus.QUEUED,
        authorized=True,
        kind="scene_image",
        target_scene_id=target.id,
        provider_cost_cap=2.0,
    )
    svc.repo.jobs[job2.id] = job2
    RealGenerationWorker(svc, dry_run=True).run_job(job2.id)
    for scene in svc.repo.scenes_for(job.project_id):
        if scene.id == target.id:
            assert scene.active_version_id == keep[scene.id]
            version = svc._active_version(scene)
            assert version.image_asset_version_id
        else:
            assert scene.active_version_id == keep[scene.id]


def test_durable_claim_and_crash_recovery() -> None:
    svc = ProductService(generation_mode="real", storage=FakeS3Storage())
    _user, job = _job(svc)
    svc.start_generation(job.user_id, job.id)
    DurableGenerationWorker(svc, worker_id="w1", generation_mode="real", dry_run=True).tick()
    assert svc.repo.jobs[job.id].status is JobStatus.COMPLETED
    DurableGenerationWorker(svc, worker_id="w2", generation_mode="real", dry_run=True).run_job_id(
        job.id
    )
    attempts = svc.repo.attempts_for_job(job.id)
    hashes = [a.request_hash for a in attempts if a.request_hash]
    assert hashes
    assert len(hashes) == len(set(hashes))


def test_object_storage_signed_urls_and_metadata() -> None:
    store = FakeS3Storage()
    store.put_bytes("finals/a.mp4", b"mp4", content_type="video/mp4")
    assert store.exists("finals/a.mp4")
    url = store.signed_url("finals/a.mp4", expires_in=120)
    assert "exp=120" in url
    assert store.metadata("finals/a.mp4")["content_type"] == "video/mp4"
    signer = S3CompatibleStorage(
        bucket="b",
        access_key="AKIA",
        secret_key="secret",
        endpoint="https://example.r2.cloudflarestorage.com",
    )
    signed = signer.signed_url("k", expires_in=60)
    assert "X-Amz-Signature=" in signed
    assert "X-Amz-Credential=" in signed


def test_media_redirects_to_signed_url() -> None:
    storage = FakeS3Storage()
    svc = ProductService(generation_mode="real", storage=storage)
    user, job = _job(svc)
    RealGenerationWorker(svc, dry_run=True).run_job(job.id)
    asset_id = svc.repo.jobs[job.id].progress["final_asset_version_id"]
    token = SessionIssuer("sess").issue(user.id, datetime.now(UTC))
    client = TestClient(create_app(service=svc, env="test", sessions=SessionIssuer("sess")))
    response = client.get(
        f"/api/v1/media/{asset_id}",
        headers={"Authorization": f"Bearer {token}"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "signed.example" in response.headers["location"]


def test_ownership_gate_on_media() -> None:
    storage = FakeS3Storage()
    svc = ProductService(generation_mode="real", storage=storage)
    _user, job = _job(svc)
    RealGenerationWorker(svc, dry_run=True).run_job(job.id)
    asset_id = svc.repo.jobs[job.id].progress["final_asset_version_id"]
    other = svc.repo.put_user(TelegramUser(telegram_user_id=2, first_name="O"))
    token = SessionIssuer("sess").issue(other.id, datetime.now(UTC))
    client = TestClient(create_app(service=svc, env="test", sessions=SessionIssuer("sess")))
    response = client.get(f"/api/v1/media/{asset_id}", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403


def test_accounted_usd_uses_attempts() -> None:
    svc = ProductService()
    user, job = _job(svc)
    svc.record_attempt(
        job.id,
        item_type=PlanItemType.STILL,
        provider="openai",
        model="gpt-image-2.5-flare",
        outcome=ProviderOutcome.SUCCEEDED,
        billed=ProviderBilledStatus.BILLED,
        estimated_provider_cost=0.05,
        actual_provider_cost=0.04,
    )
    assert accounted_usd(job, svc.repo) == 0.04


def test_hard_cap_uses_canary_limit() -> None:
    svc = ProductService(
        generation_mode="real",
        limits=ProductLimits(max_provider_usd_per_job=2.0),
    )
    _user, job = _job(svc)
    assert job.provider_cost_cap == 2.0
