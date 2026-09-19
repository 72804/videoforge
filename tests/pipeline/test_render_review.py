from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from docprod.audio.align import align_script_to_whisper
from docprod.audio.cues import chunk_alignment_cues
from docprod.audio.models import AlignedToken, AlignmentReport, WhisperWord
from docprod.audio.tts_preflight import inspect_tts_input
from docprod.exceptions import MaxPaidRequestsExceededError
from docprod.models.enums import AssetStrategy, Mood, TransitionType, VisualEffect
from docprod.models.project import Project
from docprod.models.scene import GenerationSpec, Scene, ScenePlan
from docprod.pipeline.render_review_episode import (
    _stamp_unit_progress,
    future_video_preview,
)
from docprod.pipeline.review_images import generate_review_images, plan_review_image_jobs
from docprod.production import AssetPlan, AssetUnit
from docprod.production.info_graphics import convert_info_graphic_units
from docprod.providers.image_config import ImageGenerationConfig
from docprod.providers.openai_image import OpenAIImageResult
from docprod.providers.request_budget import ModelRequestBudget
from docprod.storage.paths import ProjectPaths


def _scene(
    n: int,
    strategy: AssetStrategy,
    narration: str,
    subject: str,
    *,
    start: float = 0.0,
) -> Scene:
    prompt = "p" if strategy in {AssetStrategy.ai_image, AssetStrategy.ai_image_to_video} else None
    return Scene(
        id=f"scene_{n:04d}",
        start=start,
        end=start + 1.0,
        duration=1.0,
        narration=narration,
        visual_intent=subject,
        asset_strategy=strategy,
        effect=VisualEffect.none,
        transition=TransitionType.cut,
        mood=Mood.neutral,
        subtitle=narration,
        generation=GenerationSpec(image_prompt=prompt),
        metadata={"visual_subject": subject, "chapter": "HOOK"},
    )


def _unit(
    uid: str, scenes: list[str], strategy: AssetStrategy, status: str, concept: str
) -> AssetUnit:
    return AssetUnit(
        asset_unit_id=uid,
        scene_ids=scenes,
        source_strategy=strategy,
        continuous_duration=1.0 * len(scenes),
        visual_concept=concept,
        generation_required=strategy
        in {AssetStrategy.ai_image, AssetStrategy.ai_image_to_video},
        status=status,  # type: ignore[arg-type]
    )


def test_info_graphics_convert_photographic_remain() -> None:
    scenes = [
        _scene(1, AssetStrategy.document, "Michel Gauvreau kaydı.", "Michel Gauvreau", start=0.0),
        _scene(23, AssetStrategy.ai_image, "Kapalı fıçılar.", "closed barrels switched", start=1.0),
        _scene(33, AssetStrategy.ai_image, "Fıçı sayısı belirsiz.", "siluet grafik", start=2.0),
        _scene(34, AssetStrategy.ai_image, "Akış şeması.", "trade-channel flow", start=3.0),
        _scene(44, AssetStrategy.ai_image, "16 / yaklaşık 26.", "iki sütunlu grafik", start=4.0),
        _scene(51, AssetStrategy.ai_image, "Temyiz süreci.", "mahkeme grafiği", start=5.0),
        _scene(60, AssetStrategy.ai_image, "Blandford depo.", "warehouse montage", start=6.0),
    ]
    plan = ScenePlan(project_id="p", scenes=scenes, total_duration=7.0)
    ai = AssetStrategy.ai_image
    units = [
        _unit("au_0023", ["scene_0023"], ai, "NEEDS_AI_IMAGE", "barrels"),
        _unit("au_0033", ["scene_0033"], ai, "NEEDS_AI_IMAGE", "silhouettes"),
        _unit("au_0034", ["scene_0034"], ai, "NEEDS_AI_IMAGE", "flow"),
        _unit("au_0044", ["scene_0044"], ai, "NEEDS_AI_IMAGE", "compare"),
        _unit("au_0051", ["scene_0051"], ai, "NEEDS_AI_IMAGE", "court"),
        _unit("au_0060", ["scene_0060"], ai, "NEEDS_AI_IMAGE", "warehouse"),
        _unit("au_0001", ["scene_0001"], AssetStrategy.document, "READY_LOCAL", "named"),
    ]
    asset = AssetPlan(
        project_id="p", scene_count=7, asset_unit_count=7, saved_generation_count=0, units=units
    )
    plan, asset = convert_info_graphic_units(plan, asset)
    by_id = {scene.id: scene for scene in plan.scenes}
    assert by_id["scene_0033"].asset_strategy is AssetStrategy.ai_image
    assert by_id["scene_0034"].asset_strategy is AssetStrategy.ai_image
    assert by_id["scene_0044"].asset_strategy is AssetStrategy.ai_image
    assert by_id["scene_0051"].asset_strategy is AssetStrategy.ai_image
    assert by_id["scene_0023"].asset_strategy is AssetStrategy.ai_image
    assert by_id["scene_0060"].asset_strategy is AssetStrategy.ai_image
    assert by_id["scene_0001"].asset_strategy is not AssetStrategy.ai_image


def test_image_budget_and_cache(tmp_path: Path) -> None:
    scene = _scene(23, AssetStrategy.ai_image, "Kapalı fıçılar.", "closed barrels")
    plan = ScenePlan(project_id="p", scenes=[scene], total_duration=1.0)
    unit = _unit("au_0023", ["scene_0023"], AssetStrategy.ai_image, "NEEDS_AI_IMAGE", "barrels")
    asset = AssetPlan(
        project_id="p", scene_count=1, asset_unit_count=1, saved_generation_count=0, units=[unit]
    )
    paths = ProjectPaths(tmp_path / "proj")
    paths.root.mkdir()
    config = ImageGenerationConfig()
    jobs = plan_review_image_jobs(paths, plan=plan, asset_plan=asset, config=config, seed=1)
    assert len(jobs) == 1

    class Provider:
        def __init__(self) -> None:
            self.calls = 0

        def generate(self, prompt: str, *, confirm_paid: bool, seed=None, max_attempts=1):
            self.calls += 1
            return OpenAIImageResult(
                image_bytes=b"fake-jpeg",
                revised_prompt=None,
                usage={"total_tokens": 10},
                elapsed_seconds=0.1,
                raw_model="gpt-image-2.5-flare",
            )

    provider = Provider()
    project = Project(
        id="p",
        title="t",
        language="tr",
        target_duration_seconds=10,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        random_seed=1,
    )
    generate_review_images(
        paths,
        project=project,
        plan=plan,
        asset_plan=asset,
        confirm_paid=True,
        provider=provider,  # type: ignore[arg-type]
        budget=ModelRequestBudget(1),
    )
    assert provider.calls == 1
    jobs2 = plan_review_image_jobs(paths, plan=plan, asset_plan=asset, config=config, seed=1)
    assert jobs2[0].cached is True
    generate_review_images(
        paths,
        project=project,
        plan=plan,
        asset_plan=asset,
        confirm_paid=True,
        provider=provider,  # type: ignore[arg-type]
        budget=ModelRequestBudget(0),
    )
    assert provider.calls == 1


def test_keyframe_stored_separately() -> None:
    scene = _scene(5, AssetStrategy.ai_image_to_video, "Denetim.", "inspection")
    plan = ScenePlan(project_id="p", scenes=[scene], total_duration=1.0)
    unit = _unit(
        "au_0005_0006",
        ["scene_0005"],
        AssetStrategy.ai_image_to_video,
        "NEEDS_AI_VIDEO",
        "inspect",
    )
    asset = AssetPlan(
        project_id="p", scene_count=1, asset_unit_count=1, saved_generation_count=0, units=[unit]
    )
    jobs = plan_review_image_jobs(
        ProjectPaths(Path("/tmp/x")),
        plan=plan,
        asset_plan=asset,
        config=ImageGenerationConfig(),
        seed=1,
    )
    assert jobs[0].keyframe is True
    assert "ai_keyframes" in str(jobs[0].output_path)


def test_tts_preflight_stops_over_limit() -> None:
    assert inspect_tts_input("kısa metin").within_limit
    assert inspect_tts_input("x" * 5000).within_limit is False


def test_trailing_interpolation() -> None:
    words = "Bir iki üç dört beş altı yedi sekiz dokuz on onbir."
    plan = ScenePlan(
        project_id="p",
        scenes=[_scene(1, AssetStrategy.placeholder, words, "x")],
        total_duration=1.0,
    )
    spoken = words.replace(".", "").split()
    whisper = [
        WhisperWord(word=token, start=index * 0.2, end=index * 0.2 + 0.18)
        for index, token in enumerate(spoken[:-1])
    ]
    report = align_script_to_whisper(
        plan, whisper, language="tr", require_quality=False, audio_duration=2.4
    )
    assert report.tokens[-1].timing_source == "trailing_interpolation"
    assert report.tokens[-1].end is not None


def test_shared_unit_progress_continuous() -> None:
    scenes = [
        _scene(5, AssetStrategy.ai_image_to_video, "a", "same", start=0.0),
        _scene(6, AssetStrategy.ai_image_to_video, "b", "same", start=1.0),
    ]
    plan = ScenePlan(project_id="p", scenes=scenes, total_duration=2)
    unit = _unit(
        "au_0005_0006",
        ["scene_0005", "scene_0006"],
        AssetStrategy.ai_image_to_video,
        "NEEDS_AI_VIDEO",
        "same",
    )
    asset = AssetPlan(
        project_id="p", scene_count=2, asset_unit_count=1, saved_generation_count=1, units=[unit]
    )
    out = _stamp_unit_progress(plan, asset)
    left = out.scenes[0].metadata["unit_progress_end"]
    right = out.scenes[1].metadata["unit_progress_start"]
    assert left == right


def test_subtitle_phrase_chunking() -> None:
    tokens = [
        AlignedToken(text="Bir", scene_id="s", start=0.0, end=0.2, status="matched"),
        AlignedToken(text="adam", scene_id="s", start=0.2, end=0.4, status="matched"),
        AlignedToken(text="yürüdü.", scene_id="s", start=0.4, end=0.8, status="matched"),
        AlignedToken(text="Araba", scene_id="s", start=0.9, end=1.1, status="matched"),
        AlignedToken(text="durdu.", scene_id="s", start=1.1, end=1.4, status="matched"),
    ]
    report = AlignmentReport(
        project_id="p",
        canonical_word_count=5,
        matched_word_count=5,
        interpolated_word_count=0,
        unmatched_word_count=0,
        match_fraction=1.0,
        tokens=tokens,
        quality_passed=True,
    )
    cues = chunk_alignment_cues(report, max_chars=12)
    assert len(cues) >= 2


def test_future_video_cost_preview() -> None:
    scenes = [
        _scene(5, AssetStrategy.ai_image_to_video, "a", "inspect", start=0.0),
        _scene(6, AssetStrategy.ai_image_to_video, "b", "inspect", start=1.0),
    ]
    plan = ScenePlan(project_id="p", scenes=scenes, total_duration=2)
    unit = _unit(
        "au_0005_0006",
        ["scene_0005", "scene_0006"],
        AssetStrategy.ai_image_to_video,
        "NEEDS_AI_VIDEO",
        "inspect",
    )
    asset = AssetPlan(
        project_id="p", scene_count=2, asset_unit_count=1, saved_generation_count=1, units=[unit]
    )
    rows = future_video_preview(plan, asset)
    assert rows[0]["real_duration"] == 2.0
    assert rows[0]["sora2_720p_preview_usd"] == 0.2


def test_named_person_skipped_from_image_jobs() -> None:
    scene = _scene(1, AssetStrategy.ai_image, "Michel Gauvreau kaydı.", "Michel Gauvreau")
    plan = ScenePlan(project_id="p", scenes=[scene], total_duration=1)
    unit = _unit("au_0001", ["scene_0001"], AssetStrategy.ai_image, "NEEDS_AI_IMAGE", "portrait")
    asset = AssetPlan(
        project_id="p", scene_count=1, asset_unit_count=1, saved_generation_count=0, units=[unit]
    )
    jobs = plan_review_image_jobs(
        ProjectPaths(Path("/tmp/x")),
        plan=plan,
        asset_plan=asset,
        config=ImageGenerationConfig(),
        seed=1,
    )
    assert jobs == []


def test_sixty_seven_scenes_retained() -> None:
    scenes = [
        _scene(index, AssetStrategy.document, f"Metin {index}.", "doc", start=float(index - 1))
        for index in range(1, 68)
    ]
    plan = ScenePlan(project_id="p", scenes=scenes, total_duration=67)
    units = [
        _unit(f"au_{index:04d}", [f"scene_{index:04d}"], AssetStrategy.document, "READY_LOCAL", "x")
        for index in range(1, 68)
    ]
    asset = AssetPlan(
        project_id="p",
        scene_count=67,
        asset_unit_count=67,
        saved_generation_count=0,
        units=units,
    )
    out = _stamp_unit_progress(plan, asset)
    assert len(out.scenes) == 67
    assert [scene.id for scene in out.scenes] == [f"scene_{i:04d}" for i in range(1, 68)]


def test_cost_accounting_from_usage() -> None:
    from docprod.pipeline.render_review_episode import _image_cost_usd, _tts_cost_usd

    usd, basis = _image_cost_usd([{"input_tokens": 1_000_000, "output_tokens": 1_000_000}])
    assert usd == 35.0
    assert "measured" in basis
    tts_usd, tts_basis = _tts_cost_usd({"input_tokens": 1_000_000, "output_tokens": 1_000_000})
    assert tts_usd == 12.6
    assert "measured" in tts_basis


def test_subtitle_safe_area() -> None:
    from docprod.render.subtitles import build_ass_from_cues

    ass = build_ass_from_cues([(0.0, 1.0, "Merhaba")], play_res_x=1280, play_res_y=720)
    assert ",70,70," in ass
    assert "PlayResX: 1280" in ass


def test_zero_video_model_in_dry_run() -> None:
    from docprod.pipeline.render_review_episode import ReviewDryRun

    dry = ReviewDryRun(
        scene_count=67,
        asset_unit_count=58,
        strategy_counts={},
        paid_image_requests=7,
        tts_requests=1,
        whisper_requests=1,
        video_model_requests=0,
        image_model="gpt-image-2.5-flare",
        image_quality="medium",
        tts_model="gpt-4o-mini-tts",
        tts_voice="cedar",
        tts_chars=100,
        tts_tokens=40,
        tts_within_limit=True,
        tts_reason="",
    )
    assert dry.video_model_requests == 0


def test_info_graphic_render() -> None:
    from docprod.graphics.data import render_info_graphic

    scene = _scene(44, AssetStrategy.generated_graphic, "16 / yaklaşık 26.", "compare")
    meta = {**scene.metadata, "graphic_kind": "arrest_compare"}
    scene = scene.model_copy(update={"metadata": meta})
    image, fields, kind = render_info_graphic(scene)
    assert image.size == (1536, 864)
    assert fields["left"] == "16"
    assert "26" in fields["right"]
    assert kind == "arrest_compare"


def test_budget_exceeded() -> None:
    budget = ModelRequestBudget(0)
    with pytest.raises(MaxPaidRequestsExceededError):
        budget.reserve("image")

