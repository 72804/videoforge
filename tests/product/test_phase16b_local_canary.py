from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr
from tests.product.test_phase16_real_generation import _job
from typer.testing import CliRunner

from docprod.cli import app
from docprod.config import Settings
from docprod.product.canary_adapters import FakeCanaryAdapters
from docprod.product.canary_cost import (
    CANARY_IMAGE_QUALITY,
    CANARY_IMAGE_SIZE,
    reserve_image_usd,
    reserve_script_usd,
    reserve_tts_usd,
    veo_cost,
)
from docprod.product.canary_worker import LocalCanaryWorker, clamp_script_beats, parse_canary_script
from docprod.product.enums import AttemptStatus, JobStatus, PlanItemType
from docprod.product.errors import ProductError
from docprod.product.local_canary import (
    CANARY_HARD_CAP_USD,
    CANARY_SLUG,
    assert_canary_execute_allowed,
    check_local_canary,
    execute_local_canary,
    plan_local_canary,
    stage_b_required_env,
)
from docprod.product.models import GenerationAttempt, GenerationJob
from docprod.product.paid_ops import CostCapExceeded, assert_within_cap, must_not_resubmit
from docprod.product.real_worker import LIVE_DISABLED, RealGenerationWorker
from docprod.product.services import ProductService


def _live_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "_env_file": None,
        "generation_mode": "real",
        "real_generation_dry_run": False,
        "allow_paid_generation": True,
        "allow_paid_apis": True,
        "openai_api_key": SecretStr("sk-test"),
        "gemini_api_key": SecretStr("gem-test"),
    }
    values.update(overrides)
    return Settings(**values)


def test_stage_a_plan_is_isolated_and_under_cap() -> None:
    payload = plan_local_canary()
    assert payload["slug"] == CANARY_SLUG
    assert payload["counts"]["scene_stills"] == payload["scene_count"]
    assert payload["counts"]["character_reference_images"] == 1
    assert payload["counts"]["image_generations"] == payload["scene_count"] + 1
    assert payload["counts"]["video_shots"] <= 1
    assert payload["image_settings"]["size"] == CANARY_IMAGE_SIZE
    assert payload["image_settings"]["quality"] == CANARY_IMAGE_QUALITY
    assert payload["reserved_provider_usd"] <= CANARY_HARD_CAP_USD
    assert payload["estimated_provider_usd"] <= payload["reserved_provider_usd"]
    assert payload["provider_http_calls"] == 0


def test_stage_b_refuses_each_paid_guard() -> None:
    with pytest.raises(ProductError, match="GENERATION_MODE"):
        assert_canary_execute_allowed(Settings(_env_file=None, generation_mode="mock"))
    with pytest.raises(ProductError, match="DRY_RUN"):
        assert_canary_execute_allowed(
            Settings(
                _env_file=None,
                generation_mode="real",
                real_generation_dry_run=True,
                allow_paid_generation=True,
                allow_paid_apis=True,
            )
        )
    with pytest.raises(ProductError, match="ALLOW_PAID_GENERATION"):
        assert_canary_execute_allowed(
            Settings(
                _env_file=None,
                generation_mode="real",
                real_generation_dry_run=False,
                allow_paid_generation=False,
                allow_paid_apis=True,
            )
        )
    with pytest.raises(ProductError, match="ALLOW_PAID_APIS"):
        assert_canary_execute_allowed(
            Settings(
                _env_file=None,
                generation_mode="real",
                real_generation_dry_run=False,
                allow_paid_generation=True,
                allow_paid_apis=False,
            )
        )
    assert_canary_execute_allowed(_live_settings())
    with pytest.raises(ProductError, match="non-canary"):
        assert_canary_execute_allowed(_live_settings(), slug="customer_job")
    assert any("OPENAI_API_KEY" in row for row in stage_b_required_env())


def test_cli_plan_stage_prints_zero_spend() -> None:
    result = CliRunner().invoke(app, ["generation-canary", "--stage", "plan"])
    assert result.exit_code == 0
    assert "provider_http_calls=0" in result.stdout
    assert "Stage B not executed" in result.stdout


def test_cli_execute_stage_does_not_call_providers() -> None:
    result = CliRunner().invoke(app, ["generation-canary", "--stage", "execute"])
    assert result.exit_code == 1
    assert "requires" in result.stdout or "Stage B" in result.stdout


def test_cli_refuses_non_canary_slug() -> None:
    result = CliRunner().invoke(
        app, ["generation-canary", "--stage", "plan", "--slug", "customer_job"]
    )
    assert result.exit_code == 1
    assert "refusing non-canary" in result.stdout


def test_cli_check_mode_zero_network() -> None:
    result = CliRunner().invoke(app, ["generation-canary", "--stage", "check"])
    assert result.exit_code in {0, 1}
    assert "sk-" not in result.stdout


def test_live_disabled_still_blocks_non_canary_jobs() -> None:
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


def test_cost_reservations_are_unit_based() -> None:
    assert reserve_script_usd() == pytest.approx(0.0136)
    assert reserve_image_usd(with_reference=False) == pytest.approx(0.085)
    assert reserve_image_usd(with_reference=True) == pytest.approx(0.105)
    assert veo_cost(8) == pytest.approx(0.4)
    assert reserve_tts_usd() == pytest.approx(0.4812)
    payload = plan_local_canary()
    assert payload["reserved_provider_usd"] <= 2.0
    job = GenerationJob(project_id="p", user_id="u", plan_hash="h", provider_cost_cap=2.0)
    with pytest.raises(CostCapExceeded):
        assert_within_cap(job, 0.5, spent=1.6)


def test_script_scene_count_is_clamped() -> None:
    payload = {
        "scenes": [
            {
                "narration": f"n{i}",
                "visual": "v",
                "wants_video": True,
                "duration_seconds": 8,
            }
            for i in range(12)
        ]
    }
    beats, total = clamp_script_beats(payload)
    assert 2 <= len(beats) <= 5
    assert sum(1 for beat in beats if beat["wants_video"]) <= 1
    assert 15 <= total <= 30
    assert parse_canary_script('{"scenes":[]}') == {"scenes": []}


def test_character_reference_is_planned() -> None:
    payload = plan_local_canary()
    kinds = [item["scene_id"] for item in payload["paid_operations"]]
    assert "character_ref" in kinds


def test_stage_b_check_reports_blockers_without_http() -> None:
    report = check_local_canary(Settings(_env_file=None, generation_mode="mock"))
    assert report["provider_http_calls"] == 0
    assert report["ready"] is False
    assert report["blockers"]


def test_execute_with_fakes_uses_ledger_and_identity() -> None:
    adapters = FakeCanaryAdapters()
    result = execute_local_canary(
        settings=_live_settings(),
        adapters=adapters,
        use_ffmpeg=False,
    )
    assert result["status"] == JobStatus.COMPLETED.value
    assert adapters.video_submits == 1
    assert "script" in adapters.calls
    assert adapters.calls.count("image") >= 4
    assert "tts" in adapters.calls
    assert "CANARY" in result["summary"]


def test_veo_recovery_does_not_resubmit() -> None:
    adapters = FakeCanaryAdapters()
    attempt = GenerationAttempt(
        job_id="j",
        item_type=PlanItemType.VIDEO,
        provider="google",
        model="veo-3.1-lite-generate-preview",
        status=AttemptStatus.SUBMITTED,
        remote_operation_id="fake-veo-op-1",
        request_hash="abc",
        estimated_provider_cost=0.4,
    )
    assert must_not_resubmit(attempt)
    recovered = adapters.recover_video("motion", Path("."), scene_id="s")
    assert recovered.billed_this_run is False
    assert adapters.video_submits == 0


def test_local_canary_worker_refuses_foreign_job() -> None:
    svc = ProductService(generation_mode="real")
    _user, job = _job(svc)
    adapters = FakeCanaryAdapters()
    worker = LocalCanaryWorker(
        svc,
        adapters=adapters,
        work_root=Path("/tmp"),
        final_path=Path("/tmp/x.mp4"),
        slug=CANARY_SLUG,
        dry_run=False,
        allow_paid_generation=True,
        allow_paid_apis=True,
        use_ffmpeg=False,
    )
    worker.run_job(job.id)
    assert svc.repo.jobs[job.id].status is JobStatus.FAILED
    assert adapters.calls == []
