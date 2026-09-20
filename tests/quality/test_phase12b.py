from __future__ import annotations

from pathlib import Path

import pytest

from docprod.config import Settings, require_paid_call_allowed
from docprod.drama.planner import compile_drama_scene_plan
from docprod.drama.story import build_birko_script
from docprod.exceptions import DocumentedUnimplementedError, PaidApiDisabledError
from docprod.providers.elevenlabs_sfx import ElevenLabsSFXProvider, build_sfx_payload
from docprod.providers.elevenlabs_tts import ElevenLabsTTSProvider, build_tts_payload
from docprod.providers.higgsfield import (
    HiggsfieldGenjutsuAdapter,
    HiggsfieldKlingAdapter,
    genjutsu_cache_hash,
    preflight_genjutsu,
)
from docprod.providers.paid_cache import video_cache_hash
from docprod.providers.runway_video import (
    RunwayVideoProvider,
    build_act_two_payload,
    build_gen45_payload,
)
from docprod.quality.budget import allocate_video
from docprod.quality.catalog import get_model
from docprod.quality.cost_plan import build_cost_plan
from docprod.quality.driving import driving_plan_for, needs_driving_performance
from docprod.quality.duration import billable_seconds, trim_to_scene_window
from docprod.quality.enums import AdapterStatus, CostConfidence, QualityProfile
from docprod.quality.substitution import (
    episode_output_name,
    plan_substitution,
)
from docprod.quality.tts_compare import compare_narrators
from docprod.render.still import resolve_upgrade_clip


def test_runway_and_eleven_pricing_loaded() -> None:
    gen = get_model("runway-gen-4.5")
    act = get_model("runway-act-two")
    tts = get_model("eleven-v3")
    sfx = get_model("eleven-sfx")
    music = get_model("eleven-music")
    assert gen and gen.pricing.confidence is CostConfidence.KNOWN
    assert gen.pricing.value == pytest.approx(0.12)
    assert act and act.pricing.value == pytest.approx(0.05)
    assert tts and tts.implemented
    assert sfx and sfx.pricing.value == pytest.approx(0.12)
    assert music and music.implemented
    assert get_model("higgsfield-genjutsu").adapter_status is AdapterStatus.DOCUMENTED_UNIMPLEMENTED


def test_billable_vs_used_seconds() -> None:
    assert billable_seconds("veo-3.1-lite-generate-preview", 3.8) == 8.0
    assert billable_seconds("runway-gen-4.5", 3.8) == 4.0
    assert billable_seconds("runway-act-two", 4.2) == 5.0
    assert trim_to_scene_window(8.0, 3.8) == 3.8


def test_gen45_and_act_two_payloads() -> None:
    i2v = build_gen45_payload(prompt="walk", image_uri="https://example.com/a.jpg", duration=4)
    assert i2v["json"]["model"] == "gen4.5"
    assert i2v["estimated_usd"] == pytest.approx(0.48)
    act = build_act_two_payload(
        character_image_uri="https://example.com/c.jpg",
        driving_video_uri="https://example.com/d.mp4",
        driving_seconds=6,
    )
    assert act["json"]["model"] == "act_two"
    assert act["json"]["bodyControl"] is True
    assert act["billable_seconds"] == 6.0
    dry = RunwayVideoProvider().generate_act_two(
        character_image=Path("/no.jpg"),
        driving_video=Path("/no.mp4"),
        confirm_paid=False,
        driving_seconds=5,
        dry_run=True,
        use_cache=False,
    )
    assert dry["paid_calls"] == 0


def test_eleven_tts_sfx_dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "voice_test")
    from docprod.config import Settings

    settings = Settings(_env_file=None, elevenlabs_voice_id="voice_test")
    payload = build_tts_payload(text="Merhaba.", voice_id="voice_test", language="tr")
    assert payload["json"]["model_id"] == "eleven_v3"
    assert payload["json"]["language_code"] == "tr"
    tts = ElevenLabsTTSProvider(settings=settings)
    out = tts.synthesize("Merhaba.", confirm_paid=False, dry_run=True, use_cache=False)
    assert out["paid_calls"] == 0
    sfx = build_sfx_payload(prompt="ledger slam", duration_seconds=1.0)
    assert sfx["json"]["model_id"] == "eleven_text_to_sound_v2"
    sfx_out = ElevenLabsSFXProvider(settings=settings).generate(
        "ledger slam", duration_seconds=1.0, confirm_paid=False, dry_run=True, use_cache=False
    )
    assert sfx_out["dry_run"] is True


def test_genjutsu_unimplemented_and_cache() -> None:
    script = build_birko_script(project_id="tiny_drama")
    plan = compile_drama_scene_plan(script)
    scene = next(s for s in plan.scenes if s.metadata.get("beat_id") == "b07")
    from docprod.quality.shots import performance_request_for

    req = performance_request_for(scene)
    # b07 is dialogue, not performance — use a performance scene
    scene_p = next(s for s in plan.scenes if s.metadata.get("beat_id") == "b18")
    req = performance_request_for(scene_p)
    assert req is not None
    planned = HiggsfieldGenjutsuAdapter().plan(req, dry_run=True)
    assert planned["adapter_status"] == "documented_unimplemented"
    assert "docs.higgsfield.ai" in planned["reason"]
    a = genjutsu_cache_hash(
        driving_sha="aaa",
        ref_shas=["r1"],
        audio_sha="",
        duration=6,
        resolution="1080p",
        config={},
    )
    b = genjutsu_cache_hash(
        driving_sha="bbb",
        ref_shas=["r1"],
        audio_sha="",
        duration=6,
        resolution="1080p",
        config={},
    )
    assert a != b
    with pytest.raises(DocumentedUnimplementedError):
        HiggsfieldKlingAdapter().generate_video()
    errors = preflight_genjutsu(driving_video=None, duration=40, reference_count=0)
    assert errors


def test_driving_plan_text() -> None:
    script = build_birko_script(project_id="tiny_drama")
    plan = compile_drama_scene_plan(script)
    scene = next(s for s in plan.scenes if s.metadata.get("beat_id") == "b07")
    plan_doc = driving_plan_for(scene)
    text = plan_doc.recording_instructions
    assert "Kemal" in text or "yaz" in text.casefold()
    assert plan_doc.needs_driving_performance is True
    assert needs_driving_performance(scene, model_id="runway-act-two") is True


def test_cost_bounds_unresolved_not_cheaper() -> None:
    script = build_birko_script(project_id="tiny_drama")
    plan = compile_drama_scene_plan(script)
    decisions = allocate_video(plan, QualityProfile.PREMIUM)
    cost = build_cost_plan(
        project_id="tiny_drama", profile=QualityProfile.PREMIUM, decisions=decisions
    )
    if not cost.fully_priced:
        assert cost.estimated_upper_bound_usd is None
    balanced = allocate_video(plan, QualityProfile.BALANCED)
    bcost = build_cost_plan(
        project_id="tiny_drama", profile=QualityProfile.BALANCED, decisions=balanced
    )
    assert bcost.fully_priced is True
    assert bcost.known_cost <= 5.0
    assert bcost.known_cost >= 1.0


def test_v2_reuse_and_substitution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert episode_output_name(version=1) == "birko_kemal_drama_v1.mp4"
    assert episode_output_name(version=2) == "birko_kemal_drama_v2.mp4"
    script = build_birko_script(project_id="tiny_drama")
    plan = compile_drama_scene_plan(script)
    scene = plan.scenes[0]
    sub = plan_substitution(scene, clip_duration=8.0)
    assert sub.timing_unchanged is True
    assert sub.trim_to == pytest.approx(min(8.0, scene.duration))
    from docprod.storage.paths import ProjectPaths

    paths = ProjectPaths(tmp_path)
    (paths.visuals_dir / "upgrades").mkdir(parents=True)
    clip = paths.visuals_dir / "upgrades" / f"{scene.id}.mp4"
    clip.write_bytes(b"not-a-real-mp4")
    visual = resolve_upgrade_clip(paths, scene)
    assert visual is not None
    assert visual.kind == "ai_video"


def test_tts_compare_cached_openai() -> None:
    rows = compare_narrators(character_count=2000, speech_minutes=2.0, cached_openai=True)
    by_id = {r.model_id: r for r in rows}
    assert by_id["gpt-4o-mini-tts"].estimated_cost == 0.0
    assert "re-align" in by_id["eleven-v3"].downstream


def test_no_paid_when_confirm_false() -> None:
    cfg = Settings(_env_file=None, allow_paid_apis=False)
    with pytest.raises(PaidApiDisabledError):
        require_paid_call_allowed("runway", confirm_paid=True, settings=cfg)


def test_video_hash_includes_driving() -> None:
    a = video_cache_hash(
        model="act_two",
        prompt="act_two",
        negative_prompt="",
        input_image_sha256s=["c"],
        reference_image_sha256s=[],
        driving_video_sha256="drive1",
        audio_sha256="",
        duration_seconds=5,
        resolution="1280:720",
        aspect_ratio="16:9",
    )
    b = video_cache_hash(
        model="act_two",
        prompt="act_two",
        negative_prompt="",
        input_image_sha256s=["c"],
        reference_image_sha256s=[],
        driving_video_sha256="drive2",
        audio_sha256="",
        duration_seconds=5,
        resolution="1280:720",
        aspect_ratio="16:9",
    )
    assert a != b
