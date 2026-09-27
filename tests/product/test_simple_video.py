from __future__ import annotations

from pathlib import Path

import pytest

from docprod.exceptions import PaidApiNotConfirmedError
from docprod.product.errors import ProductError
from docprod.product.simple_video import (
    MAX_SCENES,
    MIN_SCENES,
    SIMPLE_VIDEO_HARD_CAP_USD,
    SimpleScene,
    SimpleScript,
    SimpleVideoJob,
    build_simple_video_jobs,
    concat_simple_scenes,
    dialogue_line_count,
    envelope_video_cost,
    example_simple_script,
    execute_simple_script_generate,
    execute_simple_script_plan,
    execute_simple_video_generate,
    execute_simple_video_plan,
    kling_fallback_body,
    mark_scene_succeeded,
    next_unfinished_scene,
    refs_for_scene,
    validate_simple_script,
)
from docprod.product.story_pipeline import inspect_locked_character_refs, locked_episode_brief
from docprod.providers.higgsfield import (
    SEEDANCE_CONTRACTS,
    higgsfield_credentials_present,
    seedance_reference_to_video_body,
)
from docprod.render.ffmpeg import run_ffmpeg


def test_six_to_eight_scenes_not_twenty_eight() -> None:
    script = example_simple_script()
    assert MIN_SCENES <= len(script.scenes) <= MAX_SCENES
    assert len(script.scenes) != 28
    validate_simple_script(script)
    bloated = SimpleScript(
        scenes=[
            SimpleScene(
                scene_id=f"S{index}",
                duration=5.0,
                visible_character_ids=["kemal"],
                dialogue_lines=[],
            )
            for index in range(28)
        ]
    )
    with pytest.raises(ProductError, match="6–8 scenes"):
        validate_simple_script(bloated)


def test_dialogue_and_cast_limits() -> None:
    script = example_simple_script()
    assert 8 <= dialogue_line_count(script) <= 12
    assert all(len(scene.visible_character_ids) <= 3 for scene in script.scenes)
    crowded = example_simple_script()
    crowded.scenes[0].visible_character_ids = ["a", "b", "c", "d"]
    with pytest.raises(ProductError, match="visible cast"):
        validate_simple_script(crowded)


def test_locked_refs_map_to_visible_cast() -> None:
    refs = inspect_locked_character_refs()
    script = example_simple_script()
    ref_map = {str(row["slug"]): str(row["resolved_path"]) for row in refs}
    kemal = next(scene for scene in script.scenes if scene.scene_id == "S1")
    pairs = refs_for_scene(kemal, ref_map)
    assert pairs == [("kemal", ref_map["kemal"])]
    jobs = build_simple_video_jobs(script, refs)
    birko = next(job for job in jobs if job.scene_id == "S7")
    assert birko.character_ref_ids == ["birko"]
    assert "ref_birko.jpg" in birko.character_ref_paths[0]
    assert all(len(job.character_ref_ids) <= 3 for job in jobs)


def test_seedance_request_is_portrait_720p() -> None:
    body = seedance_reference_to_video_body(
        prompt="café two-shot",
        duration=8,
        image_urls=["file:///tmp/ref_kemal.jpg"],
        audio_urls=["file:///tmp/line.wav"],
    )
    assert body["aspect_ratio"] == "9:16"
    assert body["resolution"] == "720p"
    assert body["duration"] == 8
    assert body["image_urls"] == ["file:///tmp/ref_kemal.jpg"]
    assert body["audio_urls"] == ["file:///tmp/line.wav"]
    fields = SEEDANCE_CONTRACTS["seedance-2.5-reference-to-video"]["fields"]
    assert "image_urls" in fields
    assert "audio_urls" in fields
    with pytest.raises(ValueError, match="720p"):
        seedance_reference_to_video_body(
            prompt="x", duration=8, image_urls=[], resolution="1080p"
        )


def test_kling_is_secondary_only() -> None:
    job = SimpleVideoJob(
        scene_id="S1",
        prompt="x",
        duration=8,
        character_ref_paths=["/tmp/ref_kemal.jpg"],
    )
    body = kling_fallback_body(job)
    assert body["image_url"].endswith("ref_kemal.jpg")
    assert job.fallback_model == "kling-3.0-pro-image-to-video"
    assert job.model == "seedance-2.5-reference-to-video"


def test_scene_resume_skips_succeeded() -> None:
    script = example_simple_script()
    refs = inspect_locked_character_refs()
    jobs = build_simple_video_jobs(script, refs)
    ledger: dict = {"operations": {}}
    mark_scene_succeeded(
        ledger, jobs[0], artifact="s1.mp4", request_id="req-1", cost=1.0
    )
    mark_scene_succeeded(
        ledger, jobs[1], artifact="s2.mp4", request_id="req-2", cost=1.0
    )
    assert next_unfinished_scene(ledger, jobs) == jobs[2].scene_id
    for job in jobs:
        mark_scene_succeeded(ledger, job, artifact="x.mp4", request_id="r", cost=0)
    assert next_unfinished_scene(ledger, jobs) is None


def test_simple_concat_hard_cuts_without_padding(tmp_path: Path) -> None:
    clips = []
    for index in range(2):
        path = tmp_path / f"s{index}.mp4"
        run_ffmpeg(
            [
                "-f",
                "lavfi",
                "-i",
                "color=c=green:s=1080x1920:d=2:r=24",
                "-pix_fmt",
                "yuv420p",
                "-an",
                "-c:v",
                "libx264",
                str(path),
            ],
            timeout=40,
        )
        clips.append(path)
    dest = tmp_path / "out.mp4"
    concat_simple_scenes(clips, dest)
    assert dest.is_file()
    assert "duration" not in dest.with_suffix(".txt").read_text(encoding="utf-8")


def test_planning_is_zero_http() -> None:
    brief = locked_episode_brief()
    refs = inspect_locked_character_refs()
    script_plan = execute_simple_script_plan(brief=brief, refs=refs)
    assert script_plan["provider_http_calls"] == 0
    assert script_plan["execute"] is False
    assert "NOT 28 shots" in script_plan["prompt_instructions"]
    video_plan = execute_simple_video_plan(
        brief=brief, refs=refs, script=example_simple_script()
    )
    assert video_plan["provider_http_calls"] == 0
    assert video_plan["execute"] is False
    assert video_plan["reserved_usd"] <= SIMPLE_VIDEO_HARD_CAP_USD
    assert video_plan["cap_ok"] is True
    costs = envelope_video_cost()
    assert costs["hard_cap_usd"] == 12.0
    assert costs["reserved_usd"] <= 12.0
    with pytest.raises(PaidApiNotConfirmedError):
        execute_simple_script_generate(confirm_paid=False, brief=brief, refs=refs)
    dry = execute_simple_script_generate(
        confirm_paid=True, brief=brief, refs=refs, execute_calls=False
    )
    assert dry["provider_http_calls"] == 0
    blocked = execute_simple_video_generate(
        confirm_paid=True,
        brief=brief,
        refs=refs,
        script=example_simple_script(),
        execute_calls=False,
    )
    assert blocked["provider_http_calls"] == 0
    with pytest.raises(ProductError, match="STOP BEFORE HTTP"):
        execute_simple_video_generate(
            confirm_paid=True,
            brief=brief,
            refs=refs,
            script=example_simple_script(),
            execute_calls=True,
        )
    present = higgsfield_credentials_present()
    assert present in {True, False}


def test_jobs_include_fingerprint_and_refs() -> None:
    refs = inspect_locked_character_refs()
    jobs = build_simple_video_jobs(example_simple_script(), refs)
    assert jobs
    assert all(job.request_fingerprint for job in jobs)
    assert all(job.request_body["aspect_ratio"] == "9:16" for job in jobs)
    assert all(job.native_audio_policy == "replace_or_mix_under_dialogue" for job in jobs)
    fingerprints = {job.request_fingerprint for job in jobs}
    assert len(fingerprints) == len(jobs)
