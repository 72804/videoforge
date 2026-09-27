from __future__ import annotations

from docprod.product.models import ScriptVersion
from docprod.product.series import BIRKO_E2_TARGET_STACK
from docprod.providers.anthropic import CLAUDE_OPUS_55, AnthropicMessagesAdapter
from docprod.providers.higgsfield import (
    SEEDANCE_CONTRACTS,
    documented_higgsfield_plan,
)
from docprod.quality.ab_eval import planned_ab_batch
from docprod.quality.budget import pick_from_chain
from docprod.quality.catalog import get_model
from docprod.quality.ensemble import (
    CreativeScorecard,
    plan_and_persist_script_ensemble,
    scorecard_for_customer,
)
from docprod.quality.enums import (
    ModelReadiness,
    ProductionBackend,
    ProviderStatus,
    QualityProfile,
    SceneProductionClass,
)
from docprod.quality.motion_graphics import MotionGraphicsSpec, route_motion_graphics
from docprod.quality.motion_templates import MOTION_TEMPLATE_CATEGORIES, empty_motion_library
from docprod.quality.native_audio import native_audio_use
from docprod.quality.policy_select import script_model_for, video_model_for
from docprod.quality.registry import auto_route_allowed
from docprod.quality.router import fallback_chain, preferred_video_model
from docprod.quality.story_director import script_ensemble_plan


def test_premium_script_is_astra_opus_astra() -> None:
    plan = script_ensemble_plan(QualityProfile.PREMIUM)
    assert plan["ensemble"] is True
    assert plan["primary_model"] == "gpt-6-astra"
    assert plan["critic_model"] == "claude-opus-5-5"
    assert plan["finalizer_model"] == "gpt-6-astra"
    assert plan["treatment_count"] == 3
    max_plan = script_ensemble_plan(QualityProfile.MAX_QUALITY, flagship=True)
    assert max_plan["critic_model"] == "claude-opus-5-5"


def test_economy_and_balanced_are_single_script_model() -> None:
    eco = script_ensemble_plan(QualityProfile.ECONOMY)
    bal = script_ensemble_plan(QualityProfile.BALANCED)
    assert eco["ensemble"] is False
    assert eco["primary_model"] == "gpt-6-luna"
    assert eco["critic_model"] == ""
    assert bal["primary_model"] == "gpt-6-sol"
    assert script_model_for(QualityProfile.BALANCED) == "gpt-6-sol"


def test_ensemble_persists_on_script_without_execution() -> None:
    script = ScriptVersion(project_id="p1", body="", language="tr")
    updated, run = plan_and_persist_script_ensemble(
        script, profile=QualityProfile.PREMIUM, flagship=True
    )
    stored = updated.story_spec["ensemble"]
    assert stored["primary_model"] == "gpt-6-astra"
    assert stored["critic_model"] == CLAUDE_OPUS_55
    assert stored["executed"] is False
    assert run.treatments == []
    card = CreativeScorecard(hook_strength=8, raw_critique="hook lands")
    assert scorecard_for_customer(card) == {}


def test_higgsfield_provider_vs_vendor() -> None:
    seed = get_model("seedance-2.5-reference-to-video")
    kling = get_model("kling-3.0-motion-control-pro")
    assert seed is not None and seed.provider == "higgsfield" and seed.vendor == "bytedance"
    assert kling is not None and kling.provider == "higgsfield" and kling.vendor == "kling"
    assert seed.gateway_model_id == "bytedance/seedance-2.5/reference-to-video"
    assert seed.readiness is ModelReadiness.CATALOG_ONLY
    assert "generate_audio" in SEEDANCE_CONTRACTS["seedance-2.5-text-to-video"]["fields"]


def test_seedance_capabilities_and_no_auto_route() -> None:
    t2v = get_model("seedance-2.5-text-to-video")
    assert t2v is not None
    assert "9:16" in t2v.aspect_ratios
    assert t2v.max_duration_seconds == 30
    assert t2v.native_audio is True
    assert auto_route_allowed("seedance-2.5-text-to-video") is False
    assert auto_route_allowed("veo-3.1-lite-generate-preview") is True
    plan = documented_higgsfield_plan("seedance-2.5-video-edit")
    assert plan["paid_calls"] == 0
    assert plan["contract"]["gateway_model_id"].endswith("video-edit")


def test_motion_and_reference_routing_policy() -> None:
    status = {
        "google": ProviderStatus.CONFIGURED,
        "runway": ProviderStatus.CONFIGURED,
        "higgsfield": ProviderStatus.CONFIGURED,
    }
    motion_pref = preferred_video_model(
        SceneProductionClass.MOTION_CONTROLLED_PERFORMANCE, QualityProfile.PREMIUM
    )
    assert motion_pref == "kling-3.0-motion-control-pro"
    picked = pick_from_chain(
        fallback_chain(
            SceneProductionClass.MOTION_CONTROLLED_PERFORMANCE, QualityProfile.PREMIUM
        ),
        status,
        QualityProfile.PREMIUM,
    )
    assert picked == "local-camera"
    ref_pref = preferred_video_model(
        SceneProductionClass.MULTI_REFERENCE_SCENE, QualityProfile.PREMIUM
    )
    assert ref_pref == "seedance-2.5-reference-to-video"
    edit_pref = preferred_video_model(SceneProductionClass.VIDEO_EDIT, QualityProfile.PREMIUM)
    assert edit_pref == "seedance-2.5-video-edit"
    hero = video_model_for(SceneProductionClass.HERO_CINEMATIC, QualityProfile.PREMIUM)
    assert hero == "runway-gen-4.5"
    reaction = video_model_for(SceneProductionClass.REACTION_SHOT, QualityProfile.BALANCED)
    assert reaction == "veo-3.1-lite-generate-preview"
    hallway = video_model_for(SceneProductionClass.STATIC_KEYFRAME, QualityProfile.ECONOMY)
    assert hallway == "local-camera"
    overridden = video_model_for(
        SceneProductionClass.MULTI_REFERENCE_SCENE,
        QualityProfile.PREMIUM,
        override="seedance-2.5-reference-to-video",
    )
    assert overridden == "seedance-2.5-reference-to-video"


def test_motion_graphics_falls_back_to_ffmpeg() -> None:
    spec = MotionGraphicsSpec(
        preferred_backend=ProductionBackend.OPTIONAL_PRODUCTION_BACKEND,
        allow_optional_motion_designer=False,
    )
    assert route_motion_graphics(spec) is ProductionBackend.LOCAL_FFMPEG
    designer = get_model("higgsfield-motion-designer")
    assert designer is not None
    assert designer.production_backend is ProductionBackend.OPTIONAL_PRODUCTION_BACKEND
    assert empty_motion_library() == []
    assert "awkward_stare" in MOTION_TEMPLATE_CATEGORIES


def test_native_audio_does_not_replace_character_voices() -> None:
    assert native_audio_use("seedance-2.5-text-to-video", needs_character_dialogue=True) == (
        "replace_or_mix_under_dialogue"
    )
    assert native_audio_use("gpt-4o-mini-tts", needs_character_dialogue=False) == "discard_or_none"


def test_anthropic_adapter_is_dry_run_only() -> None:
    planned = AnthropicMessagesAdapter().generate(confirm_paid=False, dry_run=True)
    assert planned["url"].endswith("/v1/messages")
    assert planned["json"]["model"] == CLAUDE_OPUS_55
    assert planned["paid_calls"] == 0


def test_offline_ab_framework_does_not_execute() -> None:
    batch = planned_ab_batch("shot-1")
    assert batch.executed is False
    assert "runway-gen-4.5" in batch.candidate_models
    assert BIRKO_E2_TARGET_STACK["execute"] is False
    assert BIRKO_E2_TARGET_STACK["script_critic"] == "claude-opus-5-5"
