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
    assert plan.hard_cap_usd == STORY_HARD_CAP_USD
    roles = [call.role for call in plan.calls]
    assert roles == ["primary", "critic", "finalizer"]
    assert plan.calls[0].model_id == "gpt-6-astra"
    assert plan.calls[0].count == 3
    assert plan.calls[1].model_id == "claude-opus-5-5"
    assert plan.calls[2].model_id == "gpt-6-astra"


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
