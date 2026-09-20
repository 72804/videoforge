from __future__ import annotations

from pathlib import Path

import pytest

from docprod.audio.sound_models import SoundPlan
from docprod.drama.planner import TITLE_SECONDS, compile_drama_scene_plan
from docprod.drama.story import CHARACTER_REF_PLAN, build_birko_script
from docprod.drama.uniqueness import assert_unique_cinematic_visuals, collage_violations
from docprod.exceptions import DossierValidationError, SemanticPlannerError
from docprod.models.scene import ScenePlan as LoadedPlan
from docprod.pipeline.plan_custom_drama import plan_custom_drama
from docprod.pipeline.plan_story_scenes import run_plan_story_scenes
from docprod.pipeline.write_script import run_write_script
from docprod.storage.json_store import load_model
from docprod.storage.paths import ProjectPaths, ensure_project_layout


def test_script_is_short_drama_not_documentary() -> None:
    script = build_birko_script(project_id="tiny_drama")
    text = script.full_narration.casefold()
    assert 220 <= script.word_count <= 450
    assert 1.4 <= script.estimated_runtime_minutes <= 3.2
    assert "hain birko" in text
    assert "baby kemal" in text or "kemal" in text
    assert "giriş" not in text
    assert "gelişme" not in text
    assert "sonuç" not in text
    assert "x’in hikayesi" not in text
    assert len(script.outline.chapters) == 3
    titles = [chapter.title for chapter in script.outline.chapters]
    assert titles == [
        "İki İsim",
        "Birko İçeride",
        "Hesap Kapanır",
    ]
    assert "müge" in text
    assert "o öder" in text
    assert "ödemiyor" in text
    assert "herkes kendi öder" in text
    assert "yaz" in text
    assert "parfüm" in text
    assert "leyla" not in text
    assert script.beats[0].purpose.startswith("cold_open")


def test_scene_plan_unique_no_collage() -> None:
    script = build_birko_script(project_id="tiny_drama")
    plan = compile_drama_scene_plan(script)
    titles = [s for s in plan.scenes if s.metadata.get("cinematic_title_card")]
    assert 20 <= len(plan.scenes) <= 26
    assert len(titles) == 3
    assert plan.scenes[0].metadata.get("cinematic_title_card") in {None, False}
    assert all(s.duration == TITLE_SECONDS for s in titles)
    assert 0.8 <= TITLE_SECONDS <= 1.3
    assert all(s.transition.value == "dip_to_black" for s in titles)
    stills = [s for s in plan.scenes if not s.metadata.get("cinematic_title_card")]
    assert 18 <= len(stills) <= 22
    durs = [s.duration for s in stills]
    assert max(durs) <= 7.1
    assert 3.5 <= (sum(durs) / len(durs)) <= 6.2
    prompts = [s.generation.image_prompt for s in stills]
    assert len(prompts) == len(set(prompts))
    assert not collage_violations(plan)
    assert_unique_cinematic_visuals(plan)
    assert any("küpe" in beat.narration.casefold() for beat in script.beats)
    assert len(CHARACTER_REF_PLAN) == 3


def test_plan_custom_drama_zero_paid(tmp_path: Path) -> None:
    paths = ProjectPaths(root=tmp_path / "birko_kemal_drama_canary")
    ensure_project_layout(paths)
    result = plan_custom_drama(project_id="birko_kemal_drama_canary", paths=paths)
    assert result.script_words > 200
    assert result.duplicate_visuals == []
    assert result.collage_violations == []
    assert result.planned_paid["total_this_step"].startswith("$0")
    assert paths.story_script_json().is_file()
    assert paths.scene_plan_json.is_file()
    assert paths.sound_plan_json().is_file()
    assert result.review_path.is_file()
    assert len(list((paths.visuals_dir / "chapter_titles").glob("*.jpg"))) == 3
    sound = load_model(paths.sound_plan_json(), SoundPlan)
    plan = load_model(paths.scene_plan_json, LoadedPlan)
    stings = [c for c in sound.cues if c.type == "transition_sting"]
    events = [c for c in sound.cues if c.type == "event_sfx"]
    assert len(stings) >= 3
    assert any("ledger" in c.story_reason.casefold() for c in events)
    assert any("pocket" in c.story_reason.casefold() for c in events)
    assert all(
        abs(s.duration - TITLE_SECONDS) < 1e-6
        for s in plan.scenes
        if s.metadata.get("cinematic_title_card")
    )
    with pytest.raises(DossierValidationError, match="plan-custom-drama"):
        run_write_script(paths, confirm_paid=False)
    with pytest.raises(SemanticPlannerError, match="plan-custom-drama"):
        run_plan_story_scenes(paths, confirm_paid=False)


def test_title_windows_follow_cold_open() -> None:
    from docprod.audio.models import RuntimeSceneTiming, RuntimeTimeline
    from docprod.drama.timeline import (
        filter_cues_over_titles,
        insert_title_windows,
        spoken_scene_plan,
    )

    script = build_birko_script(project_id="tiny_drama")
    plan = compile_drama_scene_plan(script)
    spoken = spoken_scene_plan(plan)
    cursor = 0.0
    rows = []
    for scene in spoken.scenes:
        end = cursor + 4.0
        rows.append(
            RuntimeSceneTiming(
                scene_id=scene.id,
                start=cursor,
                end=end,
                duration=4.0,
                planned_duration=4.0,
                narration=scene.narration,
            )
        )
        cursor = end
    spoken_timeline = RuntimeTimeline(
        project_id="tiny_drama",
        audio_duration=cursor,
        total_duration=cursor,
        scenes=rows,
    )
    padded, inserts = insert_title_windows(
        plan, spoken_timeline, audio_duration=cursor, title_seconds=TITLE_SECONDS
    )
    assert padded.scenes[0].narration.strip()
    assert not padded.scenes[0].narration == ""
    titles = [
        item
        for item, scene in zip(padded.scenes, plan.scenes, strict=True)
        if scene.metadata.get("cinematic_title_card")
    ]
    assert len(titles) == 3
    assert titles[0].start > 0.5
    assert len(inserts) == 3
    assert all(abs(item.duration - TITLE_SECONDS) < 1e-6 for item in titles)
    cues = [(titles[0].start + 0.1, titles[0].end - 0.1, "should hide")]
    windows = [(item.start, item.end) for item in titles]
    assert filter_cues_over_titles(cues, windows) == []


def test_duplicate_prompt_rejected() -> None:
    script = build_birko_script(project_id="tiny_drama")
    plan = compile_drama_scene_plan(script)
    stills = [scene for scene in plan.scenes if scene.generation.image_prompt]
    poisoned = []
    for scene in plan.scenes:
        if scene.id == stills[1].id:
            poisoned.append(scene.model_copy(update={"generation": stills[0].generation}))
        else:
            poisoned.append(scene)
    broken = plan.model_copy(update={"scenes": poisoned})
    with pytest.raises(ValueError, match="Duplicate"):
        assert_unique_cinematic_visuals(broken)
