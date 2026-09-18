from __future__ import annotations

from docprod.models.enums import AssetStrategy
from docprod.planning.classifier import classify_text
from docprod.planning.models import ContentCategory, VisualBeat
from docprod.planning.profile import ScenePlannerProfile
from docprod.planning.strategy import allocate_ai_video, preferred_strategy


def test_document_and_map_preferences() -> None:
    assert (
        preferred_strategy(ContentCategory.document, visual_bridge=False)
        is AssetStrategy.document
    )
    assert (
        preferred_strategy(ContentCategory.news, visual_bridge=False)
        is AssetStrategy.document
    )
    assert (
        preferred_strategy(ContentCategory.map_or_travel, visual_bridge=False)
        is AssetStrategy.map
    )
    assert (
        preferred_strategy(ContentCategory.location_establishing, visual_bridge=False)
        is AssetStrategy.stock_video
    )
    assert (
        preferred_strategy(ContentCategory.generic, visual_bridge=True)
        is AssetStrategy.placeholder
    )


def test_action_can_become_ai_video() -> None:
    profile = ScenePlannerProfile(max_ai_video_fraction=1.0)
    beat = VisualBeat(
        start=0.0,
        end=3.0,
        text="The man ran and escaped the police.",
        source_utterance_ids=["u1"],
        segmentation_reason="keep",
        classification=classify_text("The man ran and escaped the police.", "en"),
    )
    strategies, reasons = allocate_ai_video(
        [beat],
        [AssetStrategy.ai_image],
        ["category_action"],
        profile,
    )
    assert strategies[0] is AssetStrategy.ai_image_to_video
    assert "budget_allowed" in reasons[0]


def test_ai_video_duration_budget() -> None:
    profile = ScenePlannerProfile(max_ai_video_fraction=0.15, max_consecutive_ai_video=1)
    beats = []
    for i in range(8):
        text = "The man ran and chased the car then escaped."
        beats.append(
            VisualBeat(
                start=float(i * 4),
                end=float(i * 4 + 4),
                text=text,
                source_utterance_ids=[f"u{i}"],
                segmentation_reason="keep",
                classification=classify_text(text, "en"),
            )
        )
    strategies = [AssetStrategy.ai_image] * len(beats)
    reasons = ["action"] * len(beats)
    out, out_reasons = allocate_ai_video(beats, strategies, reasons, profile)
    video_dur = sum(
        b.duration
        for b, s in zip(beats, out, strict=True)
        if s is AssetStrategy.ai_image_to_video
    )
    total = sum(b.duration for b in beats)
    assert video_dur <= profile.max_ai_video_fraction * total + 1e-6
    assert any(s is AssetStrategy.ai_image for s in out)
    assert any("over_budget" in reason or "consecutive" in reason for reason in out_reasons)


def test_ai_video_consecutive_limit() -> None:
    profile = ScenePlannerProfile(max_ai_video_fraction=1.0, max_consecutive_ai_video=1)
    text = "He ran and escaped."
    beats = [
        VisualBeat(
            start=float(i * 3),
            end=float(i * 3 + 3),
            text=text,
            source_utterance_ids=[f"u{i}"],
            segmentation_reason="keep",
            classification=classify_text(text, "en"),
        )
        for i in range(3)
    ]
    out, _reasons = allocate_ai_video(
        beats,
        [AssetStrategy.ai_image] * 3,
        ["a"] * 3,
        profile,
    )
    flags = [s is AssetStrategy.ai_image_to_video for s in out]
    for prev, curr in zip(flags, flags[1:], strict=False):
        assert not (prev and curr)
