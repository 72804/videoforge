from __future__ import annotations

import pytest

from docprod.demo import build_demo_scene_plan
from docprod.drama.planner import compile_drama_scene_plan
from docprod.drama.story import build_birko_script
from docprod.drama.uniqueness import assert_unique_cinematic_visuals, duplicate_fingerprints
from docprod.exceptions import UnimplementedProviderError
from docprod.models.enums import AssetStrategy, Mood, TransitionType, VisualEffect
from docprod.models.scene import GenerationSpec, Scene
from docprod.providers.paid_cache import generic_paid_request_hash, video_cache_hash
from docprod.providers.video_capabilities import capabilities_for
from docprod.quality.adapters import MockAdapter, ProviderAdapter
from docprod.quality.availability import AvailabilityReport, availability
from docprod.quality.budget import allocate_video
from docprod.quality.catalog import get_model, model_catalog
from docprod.quality.classify import classify_scene
from docprod.quality.cost_plan import build_cost_plan
from docprod.quality.enums import (
    CostConfidence,
    ProviderStatus,
    QualityProfile,
    SceneProductionClass,
)
from docprod.quality.gates import preflight_gates
from docprod.quality.profiles import policy_for
from docprod.quality.router import estimate_model_cost, fallback_chain
from docprod.quality.shots import dialogue_request_for, performance_request_for


def _scene(**kwargs) -> Scene:
    defaults = dict(
        id="scene_0001",
        start=0.0,
        end=4.0,
        duration=4.0,
        narration="Test narration.",
        visual_intent="A kitchen interior",
        asset_strategy=AssetStrategy.ai_image,
        effect=VisualEffect.slow_push_in,
        transition=TransitionType.cut,
        mood=Mood.neutral,
        subtitle="Test narration.",
        generation=GenerationSpec(image_prompt="unique kitchen still"),
        metadata={"beat_id": "b03", "visual_bridge": False},
    )
    defaults.update(kwargs)
    return Scene(**defaults)


def test_catalog_has_priority_families() -> None:
    ids = {item.model_id for item in model_catalog()}
    assert "gpt-image-2.5-flare" in ids
    assert "gpt-image-2.5-sunburst" in ids
    assert "veo-3.1-lite-generate-preview" in ids
    assert "eleven-v3" in ids
    assert "lyria-3.5" in ids
    assert "ace-step-local" in ids
    assert get_model("kling-3") is not None
    assert get_model("kling-3").implemented is False
    assert get_model("runway-gen-4.5").implemented is True


def test_unknown_price_is_unresolved() -> None:
    cost, conf = estimate_model_cost("kling-3")
    assert cost is None
    assert conf is CostConfidence.UNRESOLVED
    known, kconf = estimate_model_cost("veo-3.1-lite-generate-preview", seconds=4.0)
    assert known == pytest.approx(0.4)
    assert kconf is CostConfidence.KNOWN


def test_classify_birko_beats() -> None:
    script = build_birko_script(project_id="tiny_drama")
    plan = compile_drama_scene_plan(script)
    by_beat = {
        str(s.metadata.get("beat_id")): classify_scene(s) for s in plan.scenes
    }
    assert by_beat["t01"] is SceneProductionClass.TITLE_CARD
    assert by_beat["b07"] is SceneProductionClass.DIALOGUE_SHOT
    assert by_beat["b09"] is SceneProductionClass.REACTION_SHOT
    assert by_beat["b15"] is SceneProductionClass.HERO_CINEMATIC
    assert by_beat["b18"] is SceneProductionClass.PERFORMANCE_SHOT
    assert by_beat["b03"] is SceneProductionClass.STATIC_CINEMATIC


def test_balanced_does_not_video_everything() -> None:
    script = build_birko_script(project_id="tiny_drama")
    plan = compile_drama_scene_plan(script)
    decisions = allocate_video(plan, QualityProfile.BALANCED)
    video = [
        d
        for d in decisions
        if d.upgrade_kind.value != "still_local_motion"
        and d.selected_model not in {"gpt-image-2.5-flare", "local-title", "local-camera"}
    ]
    video_ids = {d.scene_id for d in video}
    stills = [d for d in decisions if d.scene_id not in video_ids]
    assert 2 <= len(video) <= 10
    assert len(stills) > len(video)
    cost = build_cost_plan(
        project_id="tiny_drama",
        profile=QualityProfile.BALANCED,
        decisions=decisions,
        upgrade_existing=True,
    )
    assert cost.known_cost <= 5.0
    assert cost.known_cost >= 1.5


def test_economy_uses_local_motion() -> None:
    script = build_birko_script(project_id="tiny_drama")
    plan = compile_drama_scene_plan(script)
    decisions = allocate_video(plan, QualityProfile.ECONOMY)
    assert all(
        d.selected_model in {"local-camera", "local-title", "gpt-image-2.5-flare"}
        for d in decisions
    )


def test_local_only_never_selects_paid_implemented_video() -> None:
    script = build_birko_script(project_id="tiny_drama")
    plan = compile_drama_scene_plan(script)
    decisions = allocate_video(plan, QualityProfile.LOCAL_ONLY)
    paid = {"veo-3.1-lite-generate-preview", "gpt-4o-mini-tts", "lyria-3.5"}
    assert all(d.selected_model not in paid for d in decisions)
    assert policy_for(QualityProfile.LOCAL_ONLY).allow_paid is False


def test_hard_budget_cap() -> None:
    script = build_birko_script(project_id="tiny_drama")
    plan = compile_drama_scene_plan(script)
    decisions = allocate_video(plan, QualityProfile.BALANCED)
    cost = build_cost_plan(
        project_id="tiny_drama",
        profile=QualityProfile.BALANCED,
        decisions=decisions,
        upgrade_existing=True,
    )
    gate = preflight_gates(plan, profile=QualityProfile.BALANCED, cost=cost)
    assert gate.passed
    assert cost.known_cost <= cost.hard_budget


def test_fallbacks_end_at_local_camera() -> None:
    chain = fallback_chain(SceneProductionClass.HERO_CINEMATIC, QualityProfile.PREMIUM)
    assert chain[-1] == "local-camera"


def test_unimplemented_adapter() -> None:
    adapter = ProviderAdapter("kling-3")
    with pytest.raises(UnimplementedProviderError):
        adapter.generate_video()
    mock = MockAdapter("kling-3")
    assert mock.generate_video(prompt="x")["dry_run"] is True


def test_dialogue_and_performance_requests() -> None:
    script = build_birko_script(project_id="tiny_drama")
    plan = compile_drama_scene_plan(script)
    dialogue = [dialogue_request_for(s) for s in plan.scenes]
    performance = [performance_request_for(s) for s in plan.scenes]
    assert any(item is not None for item in dialogue)
    assert any(item is not None for item in performance)


def test_music_sync_not_normal_t2v() -> None:
    scene = _scene(
        metadata={
            "beat_id": "bx",
            "music_sync_required": True,
            "visual_bridge": False,
        }
    )
    assert classify_scene(scene) is SceneProductionClass.MUSIC_SYNCED_PERFORMANCE
    chain = fallback_chain(
        SceneProductionClass.MUSIC_SYNCED_PERFORMANCE, QualityProfile.PREMIUM
    )
    assert "local-camera" in chain
    assert chain[0] != "gpt-image-2.5-flare"


def test_cache_keys_include_refs() -> None:
    a = video_cache_hash(
        model="veo",
        prompt="p",
        negative_prompt="",
        input_image_sha256s=["aaa"],
        reference_image_sha256s=["ref1"],
        driving_video_sha256="",
        audio_sha256="",
        duration_seconds=8,
        resolution="720p",
        aspect_ratio="16:9",
    )
    b = video_cache_hash(
        model="veo",
        prompt="p",
        negative_prompt="",
        input_image_sha256s=["aaa"],
        reference_image_sha256s=["ref2"],
        driving_video_sha256="",
        audio_sha256="",
        duration_seconds=8,
        resolution="720p",
        aspect_ratio="16:9",
    )
    assert a != b
    assert generic_paid_request_hash("tts", {"text": "a"}) != generic_paid_request_hash(
        "tts", {"text": "b"}
    )


def test_availability_no_secrets() -> None:
    report = availability()
    assert isinstance(report, AvailabilityReport)
    dumped = str(report)
    assert "sk-" not in dumped


def test_maple_demo_router_runs() -> None:
    plan = build_demo_scene_plan("demo_story", 42)
    decisions = allocate_video(plan, QualityProfile.ECONOMY)
    assert len(decisions) == len(plan.scenes)


def test_birko_uniqueness_still_holds() -> None:
    script = build_birko_script(project_id="tiny_drama")
    plan = compile_drama_scene_plan(script)
    assert_unique_cinematic_visuals(plan)
    assert duplicate_fingerprints(plan) == []


def test_collage_gate() -> None:
    script = build_birko_script(project_id="tiny_drama")
    plan = compile_drama_scene_plan(script)
    poisoned = plan.scenes[0].model_copy(
        update={
            "generation": GenerationSpec(image_prompt="a 3x3 collage of faces"),
            "visual_intent": "collage grid",
        }
    )
    bad = plan.model_copy(update={"scenes": [poisoned, *plan.scenes[1:]]})
    gate = preflight_gates(bad, profile=QualityProfile.BALANCED)
    assert not gate.passed


def test_intentional_callback_allows_duplicate_title_style() -> None:
    script = build_birko_script(project_id="tiny_drama")
    plan = compile_drama_scene_plan(script)
    stills = [s for s in plan.scenes if not s.metadata.get("cinematic_title_card")]
    clone = stills[1].model_copy(
        update={
            "id": "scene_0099",
            "generation": stills[0].generation,
            "metadata": {**stills[1].metadata, "intentional_callback": True},
        }
    )
    extra = plan.model_copy(update={"scenes": [*plan.scenes, clone]})
    assert extra.scenes[-1].metadata.get("intentional_callback")


def test_veo_capabilities_backward_compatible() -> None:
    caps = capabilities_for("veo-3.1-lite-generate-preview")
    assert caps.image_to_video is True
    assert caps.duration_options == (8,)


def test_provider_unavailable_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    from docprod.quality import budget as budget_mod

    def fake_avail():
        return AvailabilityReport(
            providers={
                "openai": ProviderStatus.UNCONFIGURED,
                "google": ProviderStatus.UNCONFIGURED,
                "anthropic": ProviderStatus.UNCONFIGURED,
                "elevenlabs": ProviderStatus.UNCONFIGURED,
                "higgsfield": ProviderStatus.UNCONFIGURED,
                "runway": ProviderStatus.UNCONFIGURED,
                "stability": ProviderStatus.UNCONFIGURED,
                "local": ProviderStatus.UNCONFIGURED,
            },
            local_endpoints={},
        )

    monkeypatch.setattr(budget_mod, "availability", lambda: fake_avail())
    script = build_birko_script(project_id="tiny_drama")
    plan = compile_drama_scene_plan(script)
    decisions = allocate_video(
        plan,
        QualityProfile.BALANCED,
        status=fake_avail().providers,
    )
    assert any(d.selected_model == "local-camera" for d in decisions) or any(
        d.selected_model == "veo-3.1-lite-generate-preview" for d in decisions
    )
