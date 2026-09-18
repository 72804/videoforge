from __future__ import annotations

from docprod.models.enums import AssetStrategy
from docprod.planning.models import summarize_scene_plan
from docprod.planning.planner import image_prompt_for, join_prompt_parts, plan_scenes
from docprod.planning.profile import ScenePlannerProfile
from docprod.storage.hashing import content_hash
from tests.planning.helpers import PROFILE, script_from, utterance


def test_simple_utterance_to_scene() -> None:
    script = script_from(utterance("u1", "The train station was empty at night.", 0.0, 3.5))
    plan = plan_scenes(project_id="demo", script=script, random_seed=1, profile=PROFILE)
    assert len(plan.scenes) == 1
    scene = plan.scenes[0]
    assert scene.id == "scene_0001"
    assert scene.asset_strategy is AssetStrategy.stock_video
    assert "planner_version" in scene.metadata
    assert scene.metadata["source_utterance_ids"] == ["u1"]
    assert scene.subtitle == scene.narration
    assert scene.generation.image_prompt is None


def test_ai_prompts_only_for_ai_strategies() -> None:
    script = script_from(utterance("u1", "A man waited inside the room.", 0.0, 3.0))
    plan = plan_scenes(project_id="demo", script=script, random_seed=1, profile=PROFILE)
    scene = plan.scenes[0]
    if scene.asset_strategy in {AssetStrategy.ai_image, AssetStrategy.ai_image_to_video}:
        assert scene.generation.image_prompt
        assert "documentary" in scene.generation.image_prompt.lower()
        if scene.asset_strategy is AssetStrategy.ai_image:
            assert scene.generation.motion_prompt is None
        else:
            assert scene.generation.motion_prompt
    else:
        assert scene.generation.image_prompt is None


def test_document_and_map_from_planner() -> None:
    script = script_from(
        utterance("u1", "The report and newspaper clipping were evidence.", 0.0, 3.2),
        utterance("u2", "The map marked a route toward the north exit.", 3.2, 6.4),
    )
    plan = plan_scenes(project_id="demo", script=script, random_seed=2, profile=PROFILE)
    strategies = [scene.asset_strategy for scene in plan.scenes]
    assert AssetStrategy.document in strategies
    assert AssetStrategy.map in strategies


def test_deterministic_same_seed() -> None:
    script = script_from(
        utterance("u1", "A man walked through the station.", 0.0, 3.0),
        utterance("u2", "He opened the abandoned briefcase.", 3.0, 6.2),
        utterance("u3", "Police arrived after the call.", 6.2, 9.5),
    )
    a = plan_scenes(project_id="demo", script=script, random_seed=42, profile=PROFILE)
    b = plan_scenes(project_id="demo", script=script, random_seed=42, profile=PROFILE)
    assert content_hash(a) == content_hash(b)


def test_different_seed_keeps_timing() -> None:
    script = script_from(
        utterance("u1", "A man waited.", 0.0, 3.0),
        utterance("u2", "The house interior was dark.", 3.0, 6.2),
        utterance("u3", "Another generic portrait of a person.", 6.2, 9.4),
    )
    a = plan_scenes(project_id="demo", script=script, random_seed=1, profile=PROFILE)
    b = plan_scenes(project_id="demo", script=script, random_seed=99, profile=PROFILE)
    assert [(s.start, s.end) for s in a.scenes] == [(s.start, s.end) for s in b.scenes]
    for prev, curr in zip(a.scenes, a.scenes[1:], strict=False):
        assert curr.start >= prev.end - 1e-4


def test_ai_video_budget_on_action_script() -> None:
    utts = []
    t = 0.0
    for i in range(10):
        utts.append(
            utterance(
                f"u{i}",
                "The man ran, chased the car, and escaped the police.",
                t,
                t + 4.0,
            )
        )
        t += 4.0
    script = script_from(*utts)
    profile = ScenePlannerProfile(max_ai_video_fraction=0.15, max_consecutive_ai_video=1)
    plan = plan_scenes(project_id="demo", script=script, random_seed=7, profile=profile)
    stats = summarize_scene_plan(plan)
    assert stats.ai_video_fraction <= profile.max_ai_video_fraction + 1e-6
    video = [s for s in plan.scenes if s.asset_strategy is AssetStrategy.ai_image_to_video]
    still = [s for s in plan.scenes if s.asset_strategy is AssetStrategy.ai_image]
    assert video
    assert still
    assert any(
        "over_budget" in s.metadata["strategy_reason"]
        or "consecutive" in s.metadata["strategy_reason"]
        for s in still
    )


def test_variety_softens_repeated_ai_image_where_possible() -> None:
    utts = []
    t = 0.0
    for i in range(6):
        utts.append(utterance(f"u{i}", "A person stood in a quiet interior room.", t, t + 3.0))
        t += 3.0
    plan = plan_scenes(
        project_id="demo",
        script=script_from(*utts),
        random_seed=3,
        profile=PROFILE,
    )
    run = 1
    longest = 1
    prev = plan.scenes[0].asset_strategy
    for scene in plan.scenes[1:]:
        if scene.asset_strategy == prev:
            run += 1
            longest = max(longest, run)
        else:
            run = 1
        prev = scene.asset_strategy
    assert longest <= PROFILE.max_consecutive_same_strategy or all(
        scene.asset_strategy is AssetStrategy.document for scene in plan.scenes
    )


def test_bridge_empty_narration_allowed() -> None:
    script = script_from(
        utterance("u1", "The station was empty.", 0.0, 3.0),
        utterance("u2", "A man arrived later.", 5.6, 8.6),
    )
    plan = plan_scenes(project_id="demo", script=script, random_seed=1, profile=PROFILE)
    bridges = [s for s in plan.scenes if s.metadata.get("visual_bridge")]
    assert bridges
    assert bridges[0].narration == ""
    assert bridges[0].visual_intent


def test_metadata_reasons_populated() -> None:
    script = script_from(utterance("u1", "He opened the report on the table.", 0.0, 3.5))
    plan = plan_scenes(project_id="demo", script=script, random_seed=1, profile=PROFILE)
    meta = plan.scenes[0].metadata
    assert meta["strategy_reason"]
    assert meta["effect_reason"]
    assert meta["segmentation_reason"]
    assert "motion_score" in meta
    assert meta["planner_version"] == PROFILE.planner_version


def test_split_preserves_subtitle_words() -> None:
    text = (
        "The man walked through the station and opened a door then left the hall "
        "and entered another corridor after he grabbed his coat near the stairs."
    )
    script = script_from(utterance("u1", text, 0.0, 10.0, timed=True))
    plan = plan_scenes(project_id="demo", script=script, random_seed=1, profile=PROFILE)
    assert len(plan.scenes) >= 2
    combined = " ".join(scene.narration for scene in plan.scenes if scene.narration)
    for token in text.split():
        assert token in combined
    for scene in plan.scenes:
        if scene.narration:
            assert scene.subtitle == scene.narration


def test_thousand_utterances_complete() -> None:
    utts = [
        utterance(
            f"u{i}",
            f"Beat {i} on the street near a house.",
            float(i * 2.5),
            float(i * 2.5 + 2.5),
        )
        for i in range(1000)
    ]
    plan = plan_scenes(
        project_id="scale",
        script=script_from(*utts),
        random_seed=1,
        profile=PROFILE,
    )
    assert plan.scenes
    assert abs(plan.scenes[-1].end - 2500.0) <= 0.05
    for prev, curr in zip(plan.scenes, plan.scenes[1:], strict=False):
        assert curr.start >= prev.end - 1e-4


def test_prompt_punctuation_is_clean() -> None:
    joined = join_prompt_parts("A man waited.", "cinematic documentary look")
    assert ".." not in joined
    assert "?." not in joined
    assert "!." not in joined
    question = join_prompt_parts("Did he wait?", "cinematic documentary look")
    assert "?." not in question
    prompt = image_prompt_for("Documentary portrait representing: Hello.")
    assert ".." not in prompt
