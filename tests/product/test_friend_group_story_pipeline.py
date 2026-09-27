from __future__ import annotations

import pytest

from docprod.exceptions import PaidApiNotConfirmedError
from docprod.product.birko_bible import LOCKED_EPISODE_2_PREMISE, episode_2_draft_prompt
from docprod.product.errors import AuthorizationError
from docprod.product.friend_group import FriendGroupStorySpec
from docprod.product.story_pipeline import (
    STORY_GENERATE_AUTHORIZED,
    STORY_HARD_CAP_USD,
    TREATMENT_COUNT,
    build_story_generation_plan,
    execute_story_generation,
    inspect_locked_character_refs,
    locked_episode_brief,
    run_friend_group_episode,
    story_model_context,
)
from docprod.providers.pricing import (
    CLAUDE_OPUS_55_INPUT_USD_PER_MILLION,
    CLAUDE_OPUS_55_OUTPUT_USD_PER_MILLION,
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
        "claude-opus-5-5",
        "gpt-6-astra",
    ]
    astra = get_model("gpt-6-astra")
    opus = get_model("claude-opus-5-5")
    assert astra is not None and opus is not None
    assert astra.pricing.input_usd_per_million == GPT6_ASTRA_INPUT_USD_PER_MILLION == 10.0
    assert astra.pricing.output_usd_per_million == GPT6_ASTRA_OUTPUT_USD_PER_MILLION == 50.0
    assert opus.pricing.input_usd_per_million == CLAUDE_OPUS_55_INPUT_USD_PER_MILLION == 4.0
    assert opus.pricing.output_usd_per_million == CLAUDE_OPUS_55_OUTPUT_USD_PER_MILLION == 20.0
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


def test_story_generate_refuses_without_authorization() -> None:
    assert STORY_GENERATE_AUTHORIZED is False
    plan = build_story_generation_plan(locked_episode_brief())
    with pytest.raises(PaidApiNotConfirmedError):
        execute_story_generation(confirm_paid=False, plan=plan)
    with pytest.raises(AuthorizationError):
        execute_story_generation(confirm_paid=True, plan=plan)


def test_ensemble_resume_skips_completed_treatments() -> None:
    run = CreativeEnsembleRun(
        project_id="p",
        primary_model="gpt-6-astra",
        critic_model="claude-opus-5-5",
        finalizer_model="gpt-6-astra",
        treatments=["treatment-a", "treatment-b", ""],
        critic_output="",
        final_script="",
    )
    assert remaining_ensemble_stages(run) == ["treatment_3", "critic", "finalizer"]
    run.treatments[2] = "treatment-c"
    run.critic_output = "critique"
    assert remaining_ensemble_stages(run) == ["finalizer"]
