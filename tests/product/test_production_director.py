from __future__ import annotations

import json

from docprod.product.episode import EpisodeBrief, LocationBible
from docprod.product.production_director import (
    direct_friend_group_episode,
    first_executable,
    incomplete_generated_text,
    model_status_label,
    production_plans_for_profiles,
    split_action_units,
    unique_ids,
)
from docprod.product.story_artifacts import parse_friend_group_story
from docprod.quality.ensemble import CreativeEnsembleRun
from docprod.quality.enums import ModelReadiness, QualityProfile
from docprod.quality.registry import auto_route_allowed as registry_auto_route

LOCKED_PREMISE = (
    "Someone invites the group, claims others will pay, then leaves the bill behind."
)


def _payload() -> dict:
    return {
        "title": "Sadece Su",
        "tone": "cafe bill fight",
        "duration_seconds": 59,
        "cast": ["Birko", "Kemal", "Müge", "Erni", "HG", "Musti"],
        "scenes": [
            {
                "scene_id": "S1",
                "location": "Cafe interior — group table",
                "time": "now",
                "shots": [
                    {
                        "shot_id": "S1_01",
                        "framing": "receipt then Kemal",
                        "action": (
                            "3.840 TL'lik hesap Kemal'in önündedir. "
                            "Masada kahveler ve donut kutuları; Kemal'in önünde yalnızca "
                            "küçük bir su şişesi vardır. Kemal boş sandalyeye bakar."
                        ),
                        "dialogue": [
                            {
                                "character": "Kemal",
                                "line": "Ben sadece su içtim.",
                                "delivery": "quiet",
                            }
                        ],
                    }
                ],
            },
            {
                "scene_id": "S2",
                "location": "Cafe interior — same table",
                "time": "earlier",
                "shots": [
                    {
                        "shot_id": "S2_01",
                        "framing": "phone over shoulder",
                        "action": (
                            "Birko daha önce gönderdiği beş ayrı özel daveti kontrol eder. "
                            "Mesajlar sırayla belirir ve ekranda kalır. HG, Birko'nun "
                            "omzunun üzerinden okur; son iki mesajda bakışı değişir."
                        ),
                        "on_screen_text": {
                            "shared_message": "Krispy Kreme'ye gel.",
                            "private_messages": [
                                {"recipient": "Kemal", "text": "HG ısmarlıyor."},
                                {"recipient": "HG", "text": "Müge ısmarlıyor."},
                            ],
                        },
                        "dialogue": [],
                    },
                    {
                        "shot_id": "S2_03",
                        "framing": "wide table",
                        "action": (
                            "Kutular tüketilmiştir. Hesap masaya bırakılırken herkes fişe "
                            "eğilir. Birko arkalarından sıyrılıp çıkar. HG onu görür; "
                            "seslenmek yerine fişi Kemal'in önüne kaydırır. Birko'nun "
                            "elleri masa ve sandalye arkasında kalır."
                        ),
                        "dialogue": [],
                    },
                ],
            },
            {
                "scene_id": "S3",
                "location": "Cafe interior — group table",
                "time": "now",
                "shots": [
                    {
                        "shot_id": "S3_04",
                        "framing": "POS then box",
                        "action": (
                            "Kimse para çıkarmaz. Kemal kartını POS'a okutur. Müge özel "
                            "kutunun kapağını kaldırır: son yuva da boştur. Kemal "
                            "telefonundan Birko'yu arar."
                        ),
                        "dialogue": [
                            {
                                "character": "Kemal",
                                "line": "Tamam. Ödüyorum.",
                            }
                        ],
                    }
                ],
            },
            {
                "scene_id": "S4",
                "location": "Immediately outside the cafe",
                "time": "continuous",
                "shots": [
                    {
                        "shot_id": "S4_01",
                        "framing": "bench",
                        "action": (
                            "Birko rahatça oturur. Telefonu açar. Cevabının ardından aramayı "
                            "kapatıp son donuttan sakin bir ısırık alır. Son görüntü "
                            "Birko'da kalır."
                        ),
                        "dialogue": [
                            {
                                "character": "Kemal",
                                "line": "Birko! Ben sadece su içtim!",
                            },
                            {"character": "Birko", "line": "Afiyet olsun."},
                        ],
                    }
                ],
            },
        ],
    }


def _directed():
    payload = _payload()
    brief = EpisodeBrief(
        series_slug="friends",
        episode_number=2,
        title="Sadece Su",
        location="Krispy Kreme café",
        cast_names=list(payload["cast"]),
        premise=LOCKED_PREMISE,
        ending="Birko outside eating the last donut.",
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
        lighting="evening warm/cool",
        time_of_day="evening",
        props=["receipt", "premium donut box", "water bottle", "POS", "phone", "last donut"],
        spatial_layout={
            "table": "same six-top",
            "counter": "behind table",
            "window": "street glass",
            "door": "behind sightline",
            "exterior_bench": "outside same window",
            "lighting": "evening",
            "time_of_day": "evening",
        },
    )
    refs = [
        {"slug": name.casefold(), "name": name, "resolved_path": f"ref_{name.casefold()}.jpg"}
        for name in ("birko", "kemal", "muge", "erni", "hg", "musti")
    ]
    return (
        direct_friend_group_episode(
            payload,
            spec,
            brief,
            location,
            locked_refs=refs,
            profile=QualityProfile.PREMIUM,
            role_hints={
                "Birko": "quiet schemer",
                "Kemal": "victim",
                "Müge": "money",
                "Erni": "cute",
                "HG": "worsens",
                "Musti": "rage",
            },
        ),
        spec,
        brief,
        payload,
    )


def test_no_duplicate_cast_ids() -> None:
    directed, _, _, _ = _directed()
    for shot in directed.shot_plan.shots:
        assert shot.visible_cast == unique_ids(shot.visible_cast)
        assert shot.speaking_cast == unique_ids(shot.speaking_cast)
        assert shot.offscreen_speakers == unique_ids(shot.offscreen_speakers)


def test_visible_vs_offscreen_cast() -> None:
    directed, _, _, _ = _directed()
    payoff = [shot for shot in directed.shot_plan.shots if shot.scene_id == "S4"]
    assert payoff
    last = payoff[-1]
    assert "birko" in last.visible_cast
    assert "kemal" in last.offscreen_speakers or "kemal" not in last.visible_cast
    assert not (set(last.visible_cast) & set(last.offscreen_speakers))


def test_no_cast_na_when_character_present() -> None:
    directed, _, _, _ = _directed()
    for shot in directed.shot_plan.shots:
        blob = shot.action.casefold()
        named = any(
            name in blob
            for name in ("birko", "kemal", "müge", "muge", "erni", "hg", "musti")
        )
        if named:
            assert shot.visible_cast or shot.offscreen_speakers or shot.speaking_cast
            assert "n/a" not in shot.cast_refs
            assert shot.visible_cast != ["n/a"]


def test_overloaded_action_split() -> None:
    units = split_action_units(
        "Kutular tüketilmiştir. Hesap masaya bırakılırken herkes fişe eğilir. "
        "Birko arkalarından sıyrılıp çıkar. HG onu görür; seslenmek yerine fişi "
        "Kemal'in önüne kaydırır."
    )
    assert len(units) >= 4
    directed, _, _, payload = _directed()
    old = sum(len(scene["shots"]) for scene in payload["scenes"])
    s2 = [shot for shot in directed.shot_plan.shots if shot.shot_id.startswith("S2_03")]
    assert len(s2) >= 3
    assert directed.old_shot_count == old
    assert len(directed.shot_plan.shots) > directed.old_shot_count


def test_nonuniform_duration_and_bounds() -> None:
    directed, _, brief, _ = _directed()
    durations = [shot.duration_seconds for shot in directed.shot_plan.shots]
    assert max(durations) - min(durations) > 1.0
    total = sum(durations)
    lo, hi = brief.target_duration_seconds
    assert lo - 0.2 <= total <= hi + 0.2
    assert len(set(round(item, 1) for item in durations)) > 1


def test_catalog_only_cannot_be_executable() -> None:
    directed, _, _, _ = _directed()
    for shot in directed.shot_plan.shots:
        assert registry_auto_route(shot.executable_model)
        assert model_status_label(shot.executable_model) != ModelReadiness.CATALOG_ONLY.name
        assert shot.executable_model != "seedance-2.5-reference-to-video"


def test_ideal_catalog_model_may_be_recorded() -> None:
    directed, _, _, _ = _directed()
    multi = [
        shot
        for shot in directed.shot_plan.shots
        if shot.production_class == "multi_reference_scene"
    ]
    assert multi
    assert any(
        shot.ideal_model == "seedance-2.5-reference-to-video"
        and shot.ideal_status == ModelReadiness.CATALOG_ONLY.name
        for shot in multi
    )


def test_phone_text_overlay_is_local() -> None:
    directed, _, _, _ = _directed()
    overlays = [shot for shot in directed.shot_plan.shots if shot.overlay_kind == "phone_ui"]
    assert overlays
    shot = overlays[0]
    assert shot.motion_graphics_required is True
    assert shot.executable_model == "local-title"
    assert shot.overlay_copy
    assert all("ısmarlıyor" in line or "Krispy" in line for line in shot.overlay_copy)
    assert "phone" in shot.props


def test_final_donut_prop_continuity() -> None:
    directed, _, _, _ = _directed()
    empty = [
        shot
        for shot in directed.shot_plan.shots
        if "boştur" in shot.action or "tüketilmiştir" in shot.action.casefold()
    ]
    payoff = [
        shot for shot in directed.shot_plan.shots if "last donut" in shot.props
    ]
    assert empty
    assert payoff
    assert any(shot.prop_notes for shot in empty)


def test_location_continuity() -> None:
    directed, _, _, _ = _directed()
    interior = [
        shot.location_slot
        for shot in directed.shot_plan.shots
        if shot.scene_id != "S4"
    ]
    assert interior
    assert set(interior) == {"interior_table"}
    exterior = [shot for shot in directed.shot_plan.shots if shot.scene_id == "S4"]
    assert all(shot.location_slot == "exterior_bench" for shot in exterior)
    layout = directed.shot_plan.spatial_layout
    for key in ("table", "counter", "window", "door", "exterior_bench", "lighting"):
        assert layout[key]


def test_no_silent_truncation_and_final_story() -> None:
    assert incomplete_generated_text("Müge özel kutunun kapağını kaldırır: son yuva da")
    assert not incomplete_generated_text(
        "Müge özel kutunun kapağını kaldırır: son yuva da boştur."
    )
    directed, spec, brief, _ = _directed()
    visuals = " ".join(beat.visual for beat in directed.spec.scene_beats)
    assert "son yuva da boştur" in visuals
    assert directed.spec.final_story.strip() != brief.premise.strip()
    assert spec.final_story.strip() != brief.premise.strip()
    assert "Kutular tüketilmiştir" in directed.spec.final_story


def test_first_executable_skips_catalog() -> None:
    chosen = first_executable(
        ["seedance-2.5-reference-to-video", "runway-gen-4.5", "local-camera"]
    )
    assert chosen == "runway-gen-4.5"


def test_tier_plans_differ_and_have_costs() -> None:
    directed, _, _, _ = _directed()
    plans = production_plans_for_profiles(directed)
    assert plans["balanced"].expected_usd > 0
    assert plans["premium"].expected_usd > 0
    assert plans["max"].expected_usd > 0
    assert plans["max"].expected_usd >= plans["balanced"].expected_usd
    assert plans["balanced"].quality_profile == "balanced"
    exec_models = {
        key: [shot.executable_model for shot in plan.shots] for key, plan in plans.items()
    }
    assert exec_models["balanced"] != exec_models["max"] or exec_models["premium"] != exec_models[
        "balanced"
    ]
