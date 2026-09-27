from __future__ import annotations

import json
from pathlib import Path

import pytest

from docprod.exceptions import PaidApiNotConfirmedError
from docprod.product.animatic import (
    ANIMATIC_PROVIDER_HARD_CAP_USD,
    AnimaticPlan,
    apply_animatic_cap,
    build_animatic_plan,
    execute_animatic_generate,
    select_animatic_voice_backend,
)
from docprod.product.episode import (
    AnimaticKeyframeSpec,
    EpisodeBrief,
    LocationBible,
    VoiceAssignment,
)
from docprod.product.errors import ProductError
from docprod.product.production_director import direct_friend_group_episode
from docprod.product.story_artifacts import parse_friend_group_story
from docprod.quality.ensemble import CreativeEnsembleRun
from docprod.quality.enums import QualityProfile
from docprod.render.subtitles import burn_in_required, ffmpeg_subtitle_filter


def _payload() -> dict:
    return {
        "title": "Cafe Tab",
        "tone": "bill fight",
        "duration_seconds": 59,
        "cast": ["Ada", "Bob"],
        "scenes": [
            {
                "scene_id": "S1",
                "location": "Cafe interior — group table",
                "shots": [
                    {
                        "shot_id": "S1_01",
                        "action": "Ada stares at the receipt. Bob drinks water.",
                        "dialogue": [{"character": "Ada", "line": "Ben sadece su içtim."}],
                    }
                ],
            },
            {
                "scene_id": "S2",
                "location": "Cafe interior — same table",
                "shots": [
                    {
                        "shot_id": "S2_01",
                        "action": (
                            "Ada checks private invites on a phone. "
                            "Bob reads over her shoulder."
                        ),
                        "on_screen_text": {
                            "shared_message": "Kafeye gel.",
                            "private_messages": [{"recipient": "Bob", "text": "Ada ısmarlıyor."}],
                        },
                        "dialogue": [],
                    },
                    {
                        "shot_id": "S2_03",
                        "action": (
                            "Boxes look finished. The bill lands and everyone leans in. "
                            "Ada slips out. Bob notices and slides the receipt."
                        ),
                        "dialogue": [],
                    },
                ],
            },
            {
                "scene_id": "S3",
                "location": "Immediately outside the cafe",
                "shots": [
                    {
                        "shot_id": "S4_01",
                        "action": "Ada sits on the bench and eats the last donut.",
                        "dialogue": [
                            {"character": "Bob", "line": "Ada! Ben sadece su içtim!"},
                            {"character": "Ada", "line": "Afiyet olsun."},
                        ],
                    }
                ],
            },
        ],
    }


def _directed_plan():
    payload = _payload()
    brief = EpisodeBrief(
        series_slug="friends",
        episode_number=2,
        title="Cafe Tab",
        location="Krispy Kreme café",
        cast_names=["Ada", "Bob"],
        premise="Someone else was supposed to pay.",
        ending="Ada outside eating the last donut.",
        target_duration_seconds=(45.0, 60.0),
        premise_locked=True,
    )
    run = CreativeEnsembleRun(
        project_id="t",
        primary_model="gpt-6-astra",
        finalizer_model="gpt-6-astra",
        final_script=json.dumps(payload, ensure_ascii=False),
    )
    spec = parse_friend_group_story(run, brief)
    location = LocationBible(
        name="Krispy Kreme café",
        tables="six-top",
        counter="behind",
        windows="street glass",
        entrance="door",
        exterior="bench",
        lighting="evening",
        time_of_day="evening",
        props=["receipt", "premium donut box", "water bottle", "POS", "phone", "last donut"],
        spatial_layout={
            "table": "same six-top",
            "counter": "behind",
            "window": "glass",
            "door": "rear",
            "exterior_bench": "outside window",
            "lighting": "evening",
            "time_of_day": "evening",
        },
    )
    refs = [
        {"slug": "ada", "name": "Ada", "resolved_path": "/tmp/ref_ada.jpg"},
        {"slug": "bob", "name": "Bob", "resolved_path": "/tmp/ref_bob.jpg"},
    ]
    directed = direct_friend_group_episode(
        payload, spec, brief, location, locked_refs=refs, profile=QualityProfile.PREMIUM
    )
    voices = [
        VoiceAssignment(
            character_name="Ada",
            provider="elevenlabs",
            voice_id="eleven_v3_proposed_ada",
            display_name="Ada",
            fallback_voice_id="ash",
            cloning=False,
        ),
        VoiceAssignment(
            character_name="Bob",
            provider="elevenlabs",
            voice_id="eleven_v3_proposed_bob",
            display_name="Bob",
            fallback_voice_id="cedar",
            cloning=False,
        ),
    ]
    return directed, brief, location, refs, voices


def test_animatic_planning_is_generic() -> None:
    directed, brief, location, refs, voices = _directed_plan()
    plan = build_animatic_plan(
        brief=brief,
        spec=directed.spec,
        shot_plan=directed.shot_plan,
        location=location,
        locked_refs=refs,
        voices=voices,
        profile=QualityProfile.PREMIUM,
    )
    assert brief.series_slug == "friends"
    assert plan.shot_count == len(directed.shot_plan.shots)
    assert plan.unique_image_count <= plan.shot_count + 2
    assert any(item.role == "location_master" for item in plan.keyframes)
    assert plan.video_provider_calls == 0
    assert all("runway" not in kf.model for kf in plan.keyframes)


def test_two_dollar_hard_cap() -> None:
    assert ANIMATIC_PROVIDER_HARD_CAP_USD == 2.0
    over = AnimaticPlan(
        series_slug="x",
        episode_number=1,
        reserved_usd=2.01,
        hard_cap_usd=ANIMATIC_PROVIDER_HARD_CAP_USD,
    )
    capped = apply_animatic_cap(over)
    assert capped.cap_ok is False
    with pytest.raises(ProductError, match="STOP BEFORE HTTP"):
        execute_animatic_generate(capped, confirm_paid=True, work_dir=Path("/tmp"))


def test_locked_refs_preserved() -> None:
    directed, brief, location, refs, voices = _directed_plan()
    plan = build_animatic_plan(
        brief=brief,
        spec=directed.spec,
        shot_plan=directed.shot_plan,
        location=location,
        locked_refs=refs,
        voices=voices,
    )
    identity = [item for item in plan.keyframes if item.identity_critical]
    assert identity
    for item in identity:
        assert item.reference_files
        assert all("ref_" in path for path in item.reference_files)


def test_no_video_provider_calls() -> None:
    directed, brief, location, refs, voices = _directed_plan()
    plan = build_animatic_plan(
        brief=brief,
        spec=directed.spec,
        shot_plan=directed.shot_plan,
        location=location,
        locked_refs=refs,
        voices=voices,
    )
    assert plan.video_provider_calls == 0
    assert all("veo" not in kf.model and "seedance" not in kf.model for kf in plan.keyframes)


class _CountingImages:
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, keyframe: AnimaticKeyframeSpec, dest: Path) -> Path:
        self.calls += 1
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"\xff\xd8\xfffake")
        return dest


class _CountingVoices:
    def __init__(self) -> None:
        self.calls = 0

    def synthesize(self, line: object, dest: Path) -> Path:
        self.calls += 1
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"RIFF")
        return dest


class _FakeRenderer:
    def render(self, plan: AnimaticPlan, dest: Path, *, work_dir: Path) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"ftypisom")
        return dest


def test_image_and_voice_generation_resumable(tmp_path: Path) -> None:
    directed, brief, location, refs, voices = _directed_plan()
    plan = build_animatic_plan(
        brief=brief,
        spec=directed.spec,
        shot_plan=directed.shot_plan,
        location=location,
        locked_refs=refs,
        voices=voices,
    )
    images = _CountingImages()
    voices_client = _CountingVoices()
    first = execute_animatic_generate(
        plan,
        confirm_paid=True,
        work_dir=tmp_path,
        image_client=images,
        voice_client=voices_client,
        renderer=_FakeRenderer(),
        execute_calls=True,
    )
    assert first["provider_http_calls"] == images.calls + voices_client.calls
    assert images.calls == plan.unique_image_count
    second_images = _CountingImages()
    second_voices = _CountingVoices()
    second = execute_animatic_generate(
        plan,
        confirm_paid=True,
        work_dir=tmp_path,
        image_client=second_images,
        voice_client=second_voices,
        renderer=_FakeRenderer(),
        execute_calls=True,
    )
    assert second_images.calls == 0
    assert second_voices.calls == 0
    assert second["provider_http_calls"] == 0


def test_dialogue_durations_affect_edit() -> None:
    directed, brief, location, refs, voices = _directed_plan()
    long = directed.spec.model_copy(
        update={
            "dialogue_lines": [
                line.model_copy(update={"text": line.text + (" ha" * 80)})
                if "Afiyet" in line.text
                else line
                for line in directed.spec.dialogue_lines
            ]
        }
    )
    plan = build_animatic_plan(
        brief=brief,
        spec=long,
        shot_plan=directed.shot_plan,
        location=location,
        locked_refs=refs,
        voices=voices,
    )
    payoff = next(
        shot
        for shot in plan.shots
        if shot.shot_id.startswith("S4") or "donut" in shot.keyframe_id
    )
    assert payoff.edit_duration_seconds >= payoff.speech_seconds
    assert 45.0 <= plan.total_edit_seconds <= 60.0


def test_phone_text_rendered_locally(tmp_path: Path) -> None:
    directed, brief, location, refs, voices = _directed_plan()
    plan = build_animatic_plan(
        brief=brief,
        spec=directed.spec,
        shot_plan=directed.shot_plan,
        location=location,
        locked_refs=refs,
        voices=voices,
    )
    overlays = [shot for shot in plan.shots if shot.overlay_kind == "phone_ui"]
    assert overlays
    assert overlays[0].overlay_copy
    execute_animatic_generate(
        plan,
        confirm_paid=True,
        work_dir=tmp_path,
        image_client=_CountingImages(),
        voice_client=_CountingVoices(),
        renderer=_FakeRenderer(),
        execute_calls=True,
    )
    texts = list((tmp_path / "overlays").glob("*.txt"))
    assert texts
    blob = texts[0].read_text(encoding="utf-8")
    assert "ısmarlıyor" in blob or "Kafeye" in blob


def test_subtitles_burned_and_final_video(tmp_path: Path) -> None:
    directed, brief, location, refs, voices = _directed_plan()
    plan = build_animatic_plan(
        brief=brief,
        spec=directed.spec,
        shot_plan=directed.shot_plan,
        location=location,
        locked_refs=refs,
        voices=voices,
    )
    assert burn_in_required() is True
    result = execute_animatic_generate(
        plan,
        confirm_paid=True,
        work_dir=tmp_path,
        image_client=_CountingImages(),
        voice_client=_CountingVoices(),
        renderer=_FakeRenderer(),
        execute_calls=True,
    )
    assert Path(result["output"]).is_file()
    assert "subtitles=" in ffmpeg_subtitle_filter(Path(result["subtitles"]))
    assert Path(result["subtitles"]).read_text(encoding="utf-8").count("Dialogue:") >= 1


def test_location_and_prop_continuity() -> None:
    directed, brief, location, refs, voices = _directed_plan()
    plan = build_animatic_plan(
        brief=brief,
        spec=directed.spec,
        shot_plan=directed.shot_plan,
        location=location,
        locked_refs=refs,
        voices=voices,
    )
    slots = {kf.location_slot for kf in plan.keyframes}
    assert "interior_table" in slots
    assert "exterior_bench" in slots
    assert any(kf.role == "location_master" for kf in plan.keyframes)
    assert any("donut" in " ".join(shot.props) for shot in plan.shots)


def test_upgrade_recommendations_not_executed() -> None:
    directed, brief, location, refs, voices = _directed_plan()
    plan = build_animatic_plan(
        brief=brief,
        spec=directed.spec,
        shot_plan=directed.shot_plan,
        location=location,
        locked_refs=refs,
        voices=voices,
    )
    upgrades = [shot for shot in plan.shots if shot.upgrade == "VIDEO_UPGRADE_RECOMMENDED"]
    assert upgrades
    assert plan.upgrade_estimated_usd > 0
    assert plan.execute is False
    assert plan.video_provider_calls == 0


def test_generate_requires_confirm_paid(tmp_path: Path) -> None:
    directed, brief, location, refs, voices = _directed_plan()
    plan = build_animatic_plan(
        brief=brief,
        spec=directed.spec,
        shot_plan=directed.shot_plan,
        location=location,
        locked_refs=refs,
        voices=voices,
    )
    with pytest.raises(PaidApiNotConfirmedError):
        execute_animatic_generate(plan, confirm_paid=False, work_dir=tmp_path)


def test_voice_backend_falls_back_without_eleven() -> None:
    from docprod.config import Settings

    settings = Settings(elevenlabs_api_key=None, openai_api_key=None)
    assert select_animatic_voice_backend(settings, QualityProfile.PREMIUM) == (
        "gpt-4o-mini-tts"
    )
