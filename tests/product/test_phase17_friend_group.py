from __future__ import annotations

from fastapi.testclient import TestClient

from docprod.api.app import create_app
from docprod.product import social_ops
from docprod.product.engine_bridge import build_engine_spec
from docprod.product.enums import Visibility
from docprod.product.models import TelegramUser
from docprod.product.services import ProductService
from docprod.quality.catalog import get_model
from docprod.quality.enums import CapabilityMaturity, QualityProfile, SceneProductionClass
from docprod.quality.policy_select import (
    image_model_for,
    script_model_for,
    tts_model_for,
    video_model_for,
)
from docprod.quality.registry import capability_maturity
from docprod.render.subtitles import burn_in_required, ffmpeg_subtitle_filter


def _users(svc: ProductService) -> tuple[TelegramUser, TelegramUser]:
    owner = svc.repo.put_user(TelegramUser(telegram_user_id=11, first_name="Ada", username="ada"))
    other = svc.repo.put_user(TelegramUser(telegram_user_id=22, first_name="Bob", username="bob"))
    return owner, other


def test_gpt6_and_image_and_audio_policy() -> None:
    assert script_model_for(QualityProfile.ECONOMY) == "gpt-6-luna"
    assert script_model_for(QualityProfile.BALANCED) == "gpt-6-sol"
    assert script_model_for(QualityProfile.PREMIUM) == "gpt-6-astra"
    assert script_model_for(QualityProfile.MAX_QUALITY) == "gpt-6-astra"
    assert script_model_for(QualityProfile.BALANCED, flagship=True) == "gpt-6-astra"
    sunburst = "gpt-image-2.5-sunburst"
    flare = "gpt-image-2.5-flare"
    assert image_model_for(QualityProfile.ECONOMY, identity_critical=True) == flare
    assert image_model_for(QualityProfile.BALANCED, identity_critical=True) == sunburst
    assert image_model_for(QualityProfile.BALANCED, identity_critical=False) == flare
    assert image_model_for(QualityProfile.MAX_QUALITY, identity_critical=False) == sunburst
    assert tts_model_for(QualityProfile.BALANCED, dialogue=True) == "gpt-4o-mini-tts"
    assert tts_model_for(QualityProfile.PREMIUM, dialogue=True) == "eleven-v3"
    assert tts_model_for(QualityProfile.MAX_QUALITY, dialogue=True) == "eleven-v3"
    assert video_model_for(SceneProductionClass.REACTION_SHOT, QualityProfile.BALANCED) == (
        "veo-3.1-lite-generate-preview"
    )
    hero = video_model_for(SceneProductionClass.HERO_CINEMATIC, QualityProfile.PREMIUM)
    assert hero == "runway-gen-4.5"
    assert script_model_for(QualityProfile.BALANCED, override="gpt-6-luna") == "gpt-6-luna"


def test_full_veo_is_catalog_only() -> None:
    spec = get_model("veo-3.1-generate-preview")
    assert spec is not None
    assert spec.implemented is False
    assert capability_maturity("veo-3.1-generate-preview", "native_audio") is (
        CapabilityMaturity.CATALOG_CAPABILITY
    )
    assert capability_maturity("veo-3.1-lite-generate-preview", "image_to_video") is (
        CapabilityMaturity.IMPLEMENTED_CAPABILITY
    )


def test_historical_gpt56_still_catalogued() -> None:
    assert get_model("gpt-5.6-luna") is not None
    assert get_model("gpt-6-sol") is not None


def test_customer_plan_uses_policy_not_canary_hardcode() -> None:
    svc = ProductService()
    owner, _ = _users(svc)
    project = svc.create_project(owner.id, title="FG", prompt="friends at the bakkal")
    spec = build_engine_spec(
        project,
        characters=[],
        references=[],
        hard_max_usd=5.0,
        pricing=svc.pricing,
    )
    models = {item.type.value: item.model for item in spec.frozen_items}
    assert models["script"] == "gpt-6-sol"
    assert models["tts"] == "gpt-4o-mini-tts"


def test_privacy_and_cast_permission() -> None:
    svc = ProductService()
    owner, other = _users(svc)
    private = svc.create_project(owner.id, title="Secret", prompt="private joke among friends")
    friends_only = svc.create_project(
        owner.id, title="Squad", prompt="squad night at the bakkal", visibility=Visibility.FRIENDS
    )
    public = svc.create_project(
        owner.id, title="Open", prompt="public gag at the bakkal", visibility=Visibility.PUBLIC
    )
    visible = {p.id for p in social_ops.visible_projects_for_profile(svc, other, owner.id)}
    assert visible == {public.id}
    req = social_ops.request_friend(svc, other, username="ada", user_id=None)
    social_ops.respond_friend(svc, owner, req.id, accept=True)
    visible = {p.id for p in social_ops.visible_projects_for_profile(svc, other, owner.id)}
    assert visible == {friends_only.id, public.id}
    assert private.id not in visible
    other.allow_friends_to_cast_me = False
    try:
        social_ops.cast_friend_to_project(svc, owner, friends_only.id, other.id)
        raise AssertionError("cast should fail")
    except Exception as exc:
        assert "casting" in str(exc).lower()
    other.allow_friends_to_cast_me = True
    character = social_ops.cast_friend_to_project(svc, owner, friends_only.id, other.id)
    assert character.linked_user_id == other.id
    tagged = {
        p.id
        for p in social_ops.visible_projects_for_profile(
            svc, other, other.id, with_me=True
        )
    }
    assert friends_only.id in tagged
    private_cast = svc.create_project(owner.id, title="Hidden tag", prompt="private tagged hangout")
    social_ops.cast_friend_to_project(svc, owner, private_cast.id, other.id)
    tagged = {
        p.id
        for p in social_ops.visible_projects_for_profile(
            svc, other, other.id, with_me=True
        )
    }
    assert private_cast.id not in tagged


def test_blocked_user_cannot_friend() -> None:
    svc = ProductService()
    owner, other = _users(svc)
    from docprod.product.enums import FriendshipStatus
    from docprod.product.models import Friendship

    row = Friendship(
        requester_id=owner.id, addressee_id=other.id, status=FriendshipStatus.BLOCKED.value
    )
    svc.repo.friendships[row.id] = row
    try:
        social_ops.request_friend(svc, other, username="ada", user_id=None)
        raise AssertionError("blocked request should fail")
    except Exception as exc:
        text = str(exc).lower()
        assert "cannot send" in text or "friend" in text


def test_birko_import_does_not_copy_files() -> None:
    svc = ProductService()
    owner, _ = _users(svc)
    seeded = social_ops.seed_birko_foundation(svc, owner)
    names = {p.name for p in seeded["personas"]}
    assert names == {"Birko", "Kemal", "Müge"}
    for persona in seeded["personas"]:
        assert persona.locked_identity
        assert persona.external_ref_path.startswith("projects/birko_kemal_drama_canary/")
    episode = seeded["episode"]
    assert episode.title == "Birko Episode 2"
    assert episode.status.value == "draft"
    assert episode.quality_profile == "premium"


def test_story_spec_and_voices_and_subtitles() -> None:
    from docprod.product.friend_group import DialogueLineSpec, FriendGroupStorySpec, SceneBeatSpec

    svc = ProductService()
    owner, _ = _users(svc)
    project = social_ops.create_friend_group_project(
        svc, owner, prompt="hook", title="ep", quality_profile="premium"
    )
    svc.add_character(owner.id, project.id, name="Ada")
    svc.add_character(owner.id, project.id, name="Bob")
    assigned = social_ops.ensure_character_voices(svc, owner, project.id)
    assert len(set(assigned.values())) == 2
    spec = FriendGroupStorySpec(
        title="ep",
        cold_open_hook="The cola tab is wrong.",
        premise="Friends at the bakkal.",
        dialogue_lines=[
            DialogueLineSpec(speaker_character_id="a", text="Öde!", emotion="angry", scene_id="s1")
        ],
        scene_beats=[SceneBeatSpec(scene_id="s1", visual="counter")],
        payoff="Müge pays.",
    )
    from docprod.product.models import ScriptVersion

    script = ScriptVersion(project_id=project.id, body="", language="tr")
    svc.repo.scripts[script.id] = script
    project.active_script_version_id = script.id
    social_ops.attach_story_spec(svc, project, spec)
    assert script.story_spec["cold_open_hook"]
    assert svc.repo.dialogue_tracks
    mix = next(iter(svc.repo.audio_mixes.values()))
    assert mix.burn_subtitles is True
    assert burn_in_required() is True
    assert "subtitles=" in ffmpeg_subtitle_filter(__import__("pathlib").Path("captions.ass"))


def test_api_privacy_endpoints() -> None:
    app = create_app(env="test")
    client = TestClient(app)
    a = client.post("/api/v1/dev/auth", json={"telegram_user_id": 11, "first_name": "Ada"}).json()
    b = client.post("/api/v1/dev/auth", json={"telegram_user_id": 22, "first_name": "Bob"}).json()
    ha = {"Authorization": f"Bearer {a['token']}"}
    hb = {"Authorization": f"Bearer {b['token']}"}
    created = client.post(
        "/api/v1/projects",
        json={"prompt": "secret hangout night", "title": "Secret", "visibility": "PRIVATE"},
        headers=ha,
    ).json()
    listed = client.get(f"/api/v1/users/{a['user']['id']}/videos", headers=hb).json()
    assert created["id"] not in {row["id"] for row in listed}
    public = client.post(
        "/api/v1/projects",
        json={"prompt": "public hangout night", "title": "Open", "visibility": "PUBLIC"},
        headers=ha,
    ).json()
    listed = client.get(f"/api/v1/users/{a['user']['id']}/videos", headers=hb).json()
    assert public["id"] in {row["id"] for row in listed}
    missing = client.get(f"/api/v1/projects/{created['id']}/public", headers=hb)
    assert missing.status_code == 404
    me = client.patch(
        "/api/v1/me",
        json={"allow_friends_to_cast_me": True, "bio": "cast me"},
        headers=hb,
    )
    assert me.status_code == 200
    assert me.json()["allow_friends_to_cast_me"] is True
