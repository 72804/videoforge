from __future__ import annotations

import pytest
from pydantic import SecretStr

from docprod.config import Settings
from docprod.exceptions import PaidApiNotConfirmedError
from docprod.product.birko_bible import LOCKED_EPISODE_2_PREMISE, episode_2_draft_prompt
from docprod.product.errors import AuthorizationError, ProductError
from docprod.product.friend_group import FriendGroupStorySpec
from docprod.product.story_pipeline import (
    AUTHORIZED_STORY_EPISODES,
    STORY_GENERATE_AUTHORIZED,
    STORY_HARD_CAP_USD,
    TREATMENT_COUNT,
    build_story_generation_plan,
    execute_story_generation,
    inspect_locked_character_refs,
    locked_episode_brief,
    run_friend_group_episode,
    story_generation_authorized,
    story_model_context,
)
from docprod.providers.pricing import (
    CLAUDE_OPUS_55_INPUT_USD_PER_MILLION,
    GPT6_ASTRA_INPUT_USD_PER_MILLION,
    GPT6_ASTRA_OUTPUT_USD_PER_MILLION,
)
from docprod.quality.catalog import get_model
from docprod.quality.ensemble import (
    CreativeEnsembleRun,
    remaining_ensemble_stages,
)


def test_episode_2_premise_is_locked_not_screenplay() -> None:
    brief = locked_episode_brief()
    assert brief.premise_locked is True
    assert brief.engine_owns_structure is True
    assert "secretly tells each person" in brief.premise
    assert "last donut" in brief.ending
    prompt = episode_2_draft_prompt()
    assert "PREMISE LOCKED" in prompt
    assert LOCKED_EPISODE_2_PREMISE in prompt
    spec = FriendGroupStorySpec(
        title="placeholder",
        cold_open_hook="",
        premise=brief.premise,
        ending=brief.ending,
        engine_generated=False,
    )
    assert spec.scene_beats == []
    assert spec.dialogue_lines == []
    assert spec.logline == ""


def test_six_locked_refs_present_with_hashes() -> None:
    rows = inspect_locked_character_refs()
    assert {row["slug"] for row in rows} == {
        "birko",
        "kemal",
        "muge",
        "erni",
        "hg",
        "musti",
    }
    missing = [row["slug"] for row in rows if not row["present"]]
    assert missing == [], missing
    for row in rows:
        assert row["sha256"]
        assert int(row["width"]) > 0
        assert int(row["height"]) > 0
        assert "character_refs" in str(row["resolved_path"])
        assert "ref_" in str(row["resolved_path"]).lower()


def test_story_generation_plan_is_zero_media() -> None:
    plan = build_story_generation_plan(locked_episode_brief())
    assert plan.treatment_count == TREATMENT_COUNT == 3
    assert plan.execute is False
    assert plan.media_calls == 0
    assert plan.send_image_binaries is False
    assert plan.hard_cap_usd == STORY_HARD_CAP_USD
    assert len(plan.calls) == 5
    assert [call.call_id for call in plan.calls] == [
        "treatment_1",
        "treatment_2",
        "treatment_3",
        "critic",
        "finalizer",
    ]
    assert [call.model_id for call in plan.calls] == [
        "gpt-6-astra",
        "gpt-6-astra",
        "gpt-6-astra",
        "gpt-6-astra",
        "gpt-6-astra",
    ]
    critic = plan.calls[3]
    assert critic.role == "critic"
    assert "fresh independent critic" in critic.purpose
    assert critic.estimated_input_tokens == 8007
    assert critic.reserved_input_tokens == 12010
    assert critic.estimated_output_tokens == 2200
    assert critic.reserved_output_tokens == 3500
    assert critic.expected_usd == pytest.approx(0.19007, abs=1e-6)
    assert critic.reserved_usd == pytest.approx(0.29510, abs=1e-6)
    assert plan.estimated_usd == pytest.approx(0.76635, abs=1e-5)
    assert plan.reserved_usd == pytest.approx(1.17383, abs=1e-5)
    astra = get_model("gpt-6-astra")
    opus = get_model("claude-opus-5-5")
    assert astra is not None and opus is not None
    assert astra.pricing.input_usd_per_million == GPT6_ASTRA_INPUT_USD_PER_MILLION == 10.0
    assert astra.pricing.output_usd_per_million == GPT6_ASTRA_OUTPUT_USD_PER_MILLION == 50.0
    assert opus.pricing.input_usd_per_million == CLAUDE_OPUS_55_INPUT_USD_PER_MILLION == 4.0
    assert "ANTHROPIC_API_KEY is not required" in " ".join(plan.notes)
    assert plan.cost_confidence == "known"
    assert plan.reserved_usd <= STORY_HARD_CAP_USD
    assert plan.cap_ok is True
    assert plan.estimated_usd is not None
    analog = (plan.estimated_input_tokens / 1_000_000) * 15.0 + (
        plan.estimated_output_tokens / 1_000_000
    ) * 75.0
    assert abs(float(plan.estimated_usd) - analog) > 0.01


def test_story_context_excludes_image_binaries() -> None:
    context = story_model_context(locked_episode_brief(), inspect_locked_character_refs())
    blob = str(context)
    assert context["send_image_binaries"] is False
    assert "image_bytes" not in blob
    assert "\\xff\\xd8" not in blob
    assert context["reference_image_metadata"]


def test_story_plan_cli_path_writes_review_without_models() -> None:
    payload = run_friend_group_episode(stage="story-plan")
    assert payload["text_model_calls"] == 0
    assert payload["media_calls"] == 0
    assert payload["stars"] == 0
    review = payload["artifacts"]["review"]
    text = open(review, encoding="utf-8").read()
    assert "STORY NOT GENERATED" in text
    assert "ENGINE-OWNED" in text
    assert "You won't believe" not in text
    assert "claude-opus" not in text.lower()
    assert all(
        call["model_id"] == "gpt-6-astra" for call in payload["plan"]["calls"]
    )
    payload = run_friend_group_episode(stage="story-check", settings=_story_settings())
    assert payload["ready"] is True
    assert payload["readiness"]["media_generation"] is False
    assert payload["readiness"]["confirm_paid_required"] is True
    assert payload["readiness"]["anthropic_required"] is False
    assert payload["readiness"]["calls"] == 5
    assert payload["text_model_calls"] == 0


def _story_settings() -> Settings:
    return Settings(_env_file=None, openai_api_key=SecretStr("sk-test-not-a-real-key"))


def test_story_generate_requires_confirm_paid_and_allowlist() -> None:
    assert STORY_GENERATE_AUTHORIZED is False
    assert AUTHORIZED_STORY_EPISODES == {("birko", 2)}
    assert story_generation_authorized("birko", 2) is True
    assert story_generation_authorized("other", 1) is False
    plan = build_story_generation_plan(locked_episode_brief())
    settings = _story_settings()
    with pytest.raises(PaidApiNotConfirmedError):
        execute_story_generation(confirm_paid=False, plan=plan, settings=settings)
    passed = execute_story_generation(
        confirm_paid=True,
        plan=plan,
        settings=settings,
        execute_calls=False,
    )
    assert passed["authorized"] is True
    assert passed["text_model_calls"] == 0
    assert passed["media_calls"] == 0
    other = build_story_generation_plan(
        locked_episode_brief(series_slug="other", episode_number=1)
    )
    with pytest.raises(AuthorizationError):
        execute_story_generation(
            confirm_paid=True,
            plan=other,
            settings=settings,
            execute_calls=False,
        )
    over_cap = plan.model_copy(update={"reserved_usd": 3.0, "hard_cap_usd": STORY_HARD_CAP_USD})
    with pytest.raises(ProductError, match="hard cap"):
        execute_story_generation(
            confirm_paid=True,
            plan=over_cap,
            settings=settings,
            execute_calls=False,
        )


def test_mocked_story_calls_resume_without_repeating_success() -> None:
    class _Resp:
        def __init__(self, text: str) -> None:
            self.output_text = text
            self.usage = type(
                "Usage",
                (),
                {"model_dump": lambda self=None: {"input_tokens": 8, "output_tokens": 4}},
            )()

    class _Client:
        def __init__(self) -> None:
            self.calls = 0

        def create(self, **_kwargs: object) -> _Resp:
            self.calls += 1
            return _Resp(f"output-{self.calls}")

    settings = _story_settings()
    plan = build_story_generation_plan(locked_episode_brief())
    run = CreativeEnsembleRun(
        project_id="p",
        primary_model="gpt-6-astra",
        critic_model="gpt-6-astra",
        finalizer_model="gpt-6-astra",
        treatments=["kept-1", "", ""],
        critic_output="",
        final_script="",
    )
    client = _Client()
    result = execute_story_generation(
        confirm_paid=True,
        plan=plan,
        checkpoint=run,
        settings=settings,
        text_client=client,
        execute_calls=True,
        persist=False,
    )
    assert result["media_calls"] == 0
    assert client.calls == 4
    assert run.treatments[0] == "kept-1"
    assert run.treatments[1].startswith("output-")
    assert run.critic_output.startswith("output-")
    assert run.final_script.startswith("output-")
    assert remaining_ensemble_stages(run) == []


def test_ensemble_resume_skips_completed_treatments() -> None:
    run = CreativeEnsembleRun(
        project_id="p",
        primary_model="gpt-6-astra",
        critic_model="gpt-6-astra",
        finalizer_model="gpt-6-astra",
        treatments=["treatment-a", "treatment-b", ""],
        critic_output="",
        final_script="",
    )
    assert remaining_ensemble_stages(run) == ["treatment_3", "critic", "finalizer"]
    run.treatments[2] = "treatment-c"
    run.critic_output = "critique"
    assert remaining_ensemble_stages(run) == ["finalizer"]
