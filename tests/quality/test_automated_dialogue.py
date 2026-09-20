from __future__ import annotations

import pytest

from docprod.drama.planner import compile_drama_scene_plan
from docprod.drama.story import build_birko_script
from docprod.exceptions import UnimplementedProviderError
from docprod.quality.adapters import ProviderAdapter
from docprod.quality.budget import allocate_video, pick_from_chain
from docprod.quality.catalog import get_model
from docprod.quality.cost_plan import build_cost_plan
from docprod.quality.enums import ProviderStatus, QualityProfile
from docprod.quality.locked import B07_I2V_PROMPT, BIRKO_V2_BALANCED_ROUTES
from docprod.quality.router import automated_dialogue_chain
from docprod.quality.shots import audio_driven_request_for, implied_dialogue_i2v_prompt
from docprod.quality.specs import AudioDrivenDialogueRequest


def _plan():
    return compile_drama_scene_plan(build_birko_script(project_id="tiny_drama"))


def test_manual_inputs_disabled_by_default() -> None:
    plan = _plan()
    decisions = allocate_video(plan, QualityProfile.BALANCED)
    assert all(d.manual_input_required is False for d in decisions)
    assert all(d.needs_driving_performance is False for d in decisions)


def test_act_two_not_selected_without_driving_video() -> None:
    plan = _plan()
    decisions = allocate_video(plan, QualityProfile.BALANCED)
    assert all(d.selected_model != "runway-act-two" for d in decisions)
    chain = automated_dialogue_chain(QualityProfile.BALANCED)
    assert "runway-act-two" not in chain
    picked = pick_from_chain(
        ["runway-act-two", "runway-gen-4.5", "local-camera"],
        {"runway": ProviderStatus.CONFIGURED},
        QualityProfile.BALANCED,
        has_driving_video=False,
        allow_manual_inputs=False,
    )
    assert picked == "runway-gen-4.5"


def test_automated_dialogue_fallback_chain() -> None:
    chain = automated_dialogue_chain(QualityProfile.BALANCED)
    assert chain[0] == "audio-driven-lipsync"
    assert "runway-gen-4.5" in chain
    assert "veo-3.1-lite-generate-preview" in chain
    assert chain[-1] == "local-camera"
    assert get_model("audio-driven-lipsync") is not None
    assert get_model("audio-driven-lipsync").implemented is False


def test_audio_driven_dialogue_type_exists() -> None:
    plan = _plan()
    scene = next(s for s in plan.scenes if s.metadata.get("beat_id") == "b07")
    req = audio_driven_request_for(scene)
    assert isinstance(req, AudioDrivenDialogueRequest)
    assert req.accepts_target_audio is True
    assert req.lip_sync is True
    assert "Kemal" in req.dialogue_text or "yaz" in req.dialogue_text.casefold()


def test_b07_routes_to_veo_lite() -> None:
    plan = _plan()
    decisions = allocate_video(plan, QualityProfile.BALANCED)
    by_beat = {}
    for scene, decision in zip(plan.scenes, decisions, strict=True):
        beat = str((scene.metadata or {}).get("beat_id") or "")
        by_beat[beat] = decision
    assert by_beat["b07"].selected_model == "veo-3.1-lite-generate-preview"
    assert by_beat["b18"].selected_model == "veo-3.1-lite-generate-preview"
    b07 = next(s for s in plan.scenes if s.metadata.get("beat_id") == "b07")
    prompt = implied_dialogue_i2v_prompt(b07)
    assert prompt == B07_I2V_PROMPT
    assert "lip-sync" in prompt.casefold() or "lip synchronization" in prompt.casefold()


def test_cost_plan_zero_act_two() -> None:
    plan = _plan()
    decisions = allocate_video(plan, QualityProfile.BALANCED)
    cost = build_cost_plan(
        project_id="tiny_drama", profile=QualityProfile.BALANCED, decisions=decisions
    )
    assert all(d.selected_model != "runway-act-two" for d in decisions)
    assert cost.fully_priced is True
    for line in cost.lines:
        assert line.model_id != "runway-act-two"


def test_production_does_not_block_awaiting_human_video() -> None:
    plan = _plan()
    decisions = allocate_video(
        plan,
        QualityProfile.BALANCED,
        allow_manual_inputs=False,
        driving_videos={},
    )
    assert not any(d.manual_input_required for d in decisions)
    adapter = ProviderAdapter("runway-act-two")
    scene = next(s for s in plan.scenes if s.metadata.get("beat_id") == "b07")
    from docprod.quality.shots import dialogue_request_for

    req = dialogue_request_for(scene)
    assert req is not None
    with pytest.raises(UnimplementedProviderError, match="no driving video"):
        adapter.generate_dialogue(req)
    gen = ProviderAdapter("runway-gen-4.5")
    out = gen.generate_dialogue(req)
    assert out["paid_calls"] == 0
    assert BIRKO_V2_BALANCED_ROUTES["b07"] == "veo-3.1-lite-generate-preview"
