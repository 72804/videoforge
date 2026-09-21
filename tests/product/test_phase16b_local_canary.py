from __future__ import annotations

import pytest
from typer.testing import CliRunner

from docprod.cli import app
from docprod.config import Settings
from docprod.product.errors import ProductError
from docprod.product.local_canary import (
    CANARY_HARD_CAP_USD,
    CANARY_SLUG,
    assert_canary_execute_allowed,
    plan_local_canary,
    stage_b_required_env,
)


def test_stage_a_plan_is_isolated_and_under_cap() -> None:
    payload = plan_local_canary()
    assert payload["slug"] == CANARY_SLUG
    assert payload["content_kind"] == "custom_story"
    assert payload["aspect_ratio"] == "9:16"
    assert payload["quality_profile"] == "balanced"
    assert 2 <= payload["scene_count"] <= 5
    assert 15 <= payload["duration_seconds"] <= 30
    assert payload["counts"]["image_generations"] == payload["scene_count"]
    assert payload["counts"]["video_shots"] <= 1
    assert payload["counts"]["video_seconds"] in {0, 8}
    assert payload["estimated_provider_usd"] <= CANARY_HARD_CAP_USD
    assert payload["provider_http_calls"] == 0
    assert payload["stars"] == 0
    assert payload["character"] == "Nolan"
    assert "suitcase" in payload["prompt"].lower()
    path = payload["final_output"]
    assert CANARY_SLUG in path
    assert path.endswith(".mp4")


def test_stage_b_refuses_default_guards() -> None:
    with pytest.raises(ProductError):
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
    with pytest.raises(ProductError, match="LIVE_DISABLED"):
        assert_canary_execute_allowed(
            Settings(
                _env_file=None,
                generation_mode="real",
                real_generation_dry_run=False,
                allow_paid_generation=True,
                allow_paid_apis=True,
            )
        )
    assert any("OPENAI_API_KEY" in row for row in stage_b_required_env())


def test_cli_plan_stage_prints_zero_spend() -> None:
    result = CliRunner().invoke(app, ["generation-canary", "--stage", "plan"])
    assert result.exit_code == 0
    assert "provider_http_calls=0" in result.stdout
    assert "stars=0" in result.stdout
    assert "Stage B not executed" in result.stdout


def test_cli_execute_stage_does_not_call_providers() -> None:
    result = CliRunner().invoke(app, ["generation-canary", "--stage", "execute"])
    assert result.exit_code == 1
    combined = result.stdout
    assert "Stage B" in combined or "LIVE_DISABLED" in combined or "requires" in combined


def test_cli_refuses_non_canary_slug() -> None:
    result = CliRunner().invoke(
        app, ["generation-canary", "--stage", "plan", "--slug", "customer_job"]
    )
    assert result.exit_code == 1
    assert "refusing non-canary" in result.stdout
