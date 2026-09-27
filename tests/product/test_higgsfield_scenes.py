from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from docprod.config import Settings
from docprod.exceptions import PaidApiNotConfirmedError
from docprod.product.errors import ProductError
from docprod.product.friend_group import DialogueLineSpec, FriendGroupStorySpec
from docprod.product.higgsfield_scenes import (
    APPROVED_PLAN_FINGERPRINT,
    SIMPLE_VIDEO_HARD_CAP_USD,
    STORY_SPEC_RELATIVE,
    assert_higgsfield_live_authorized,
    build_higgsfield_scenes,
    execute_higgsfield_scene_generate,
    execute_higgsfield_scene_plan,
    execute_higgsfield_scene_preflight,
    format_higgsfield_cli_cost_lines,
    higgsfield_plan_fingerprint,
    load_existing_story,
    next_unfinished_higgsfield_scene,
)
from docprod.product.simple_video import concat_simple_scenes
from docprod.providers.higgsfield import seedance_reference_to_video_body
from docprod.render.ffmpeg import run_ffmpeg

_LINES = [
    ("kemal", "Ben sadece su içtim."),
    ("hg", "Şu pahalı kutudan da söyleyelim."),
    ("birko", "Söyle."),
    ("muge", "Bu özel kutuyu kim söyledi?"),
    ("kemal", "Kocan kaçmış, sen kutuyu soruyorsun!"),
    ("muge", "Fiyatını gördün mü?"),
    ("erni", "Sen karışma baby, Kemal kapatır."),
    ("erni", "Sen kapat, Müge'yle ben bölüşürüm."),
    ("kemal", "Şimdi bölüşelim."),
    ("musti", "Çocukluk arkadaşını bir hesap için mi sileceksin?"),
    ("kemal", "Sen de mi?"),
    ("musti", "Abi ya, ben berbat bi insan değilim."),
    ("kemal", "Tamam. Ödüyorum. Payınızı bugün atıyorsunuz."),
    ("kemal", "Birko! Ben sadece su içtim!"),
    ("birko", "Afiyet olsun."),
]


def _spec() -> FriendGroupStorySpec:
    return FriendGroupStorySpec(
        title="Sadece Su",
        cold_open_hook="Ben sadece su içtim.",
        premise="locked",
        dialogue_lines=[
            DialogueLineSpec(speaker_character_id=speaker, text=text)
            for speaker, text in _LINES
        ],
    )


def _refs(tmp_path: Path) -> list[dict[str, object]]:
    rows = []
    for slug in ("birko", "kemal", "muge", "erni", "hg", "musti"):
        path = tmp_path / f"ref_{slug}.jpg"
        Image.new("RGB", (64, 96), (40, 40, 40)).save(path, "JPEG")
        rows.append({"slug": slug, "resolved_path": str(path), "present": True})
    return rows


def test_existing_story_lines_are_reused(tmp_path: Path) -> None:
    plan = build_higgsfield_scenes(_spec(), _refs(tmp_path), root=tmp_path)
    used = [item.text for scene in plan.scenes for item in scene.dialogue_lines]
    assert used == [text for _speaker, text in _LINES]
    assert 6 <= len(plan.scenes) <= 8
    assert len(plan.scenes) != 28


def test_higgsfield_cli_cost_lines_use_plan_totals() -> None:
    totals, creds = format_higgsfield_cli_cost_lines(
        {
            "expected_usd": 8.64,
            "reserved_usd": 10.656,
            "hard_cap_usd": 12.0,
            "cap_ok": True,
            "higgsfield_credentials_present": False,
        }
    )
    assert totals == "expected_total=8.64 reserved_total=10.656 hard_cap_usd=12.0 cap_ok=True"
    assert creds == "higgsfield_credentials_present=false"
    assert "simple_expected" not in totals
    assert "api_key" not in creds.lower()


def test_no_astra_in_higgsfield_plan_path() -> None:
    import inspect

    from docprod.product import higgsfield_scenes as module

    source = inspect.getsource(module)
    assert "simple-script-generate" not in source
    assert "OpenAIStoryClient" not in source
    assert "gpt-6-astra" not in source
    assert "openai_tts" not in source
    assert "gpt-4o-mini-tts" not in source


def test_visible_cast_and_unique_refs(tmp_path: Path) -> None:
    plan = build_higgsfield_scenes(_spec(), _refs(tmp_path), root=tmp_path)
    for scene in plan.scenes:
        assert 1 <= len(scene.visible_characters) <= 3
        assert len(scene.character_refs) == len(set(scene.character_refs))
        assert len(scene.character_refs) == len(scene.visible_characters)
        assert "zoompan" not in scene.video_prompt
        assert 5 <= scene.duration <= 10
        assert scene.model == "seedance-2.5-reference-to-video"


def test_seedance_native_audio_not_external_tts(tmp_path: Path) -> None:
    plan = build_higgsfield_scenes(_spec(), _refs(tmp_path), root=tmp_path)
    assert plan.native_audio is True
    assert plan.external_tts is False
    names = {
        "birko": "Birko",
        "kemal": "Kemal",
        "muge": "Müge",
        "erni": "Erni",
        "hg": "HG",
        "musti": "Musti",
    }
    used = [item.text for scene in plan.scenes for item in scene.dialogue_lines]
    assert used == [text for _speaker, text in _LINES]
    for scene in plan.scenes:
        body = scene.request_body
        assert body["generate_audio"] is True
        assert "audio_urls" not in body
        assert scene.generate_audio is True
        assert scene.native_audio is True
        assert scene.external_tts is False
        assert scene.audio_track == []
        for item in scene.dialogue_lines:
            quoted = f'{names[item.speaker]} says EXACTLY these Turkish words: "{item.text}"'
            assert quoted in scene.video_prompt
            assert "Character bible:" in item.voice
        if scene.dialogue_lines:
            assert "lip-synced Turkish" in scene.video_prompt
        else:
            assert "Do not invent lines." in scene.video_prompt
    from docprod.product.higgsfield_scenes import format_higgsfield_review

    review = format_higgsfield_review(plan, {slug: {"use": ""} for slug in names})
    assert "native_audio=true" in review
    assert "external_tts=false" in review


def test_seedance_construction_and_resume(tmp_path: Path) -> None:
    plan = build_higgsfield_scenes(_spec(), _refs(tmp_path), root=tmp_path)
    body = seedance_reference_to_video_body(
        prompt=plan.scenes[0].video_prompt,
        duration=plan.scenes[0].duration,
        image_urls=plan.scenes[0].request_body["image_urls"],
    )
    assert body["aspect_ratio"] == "9:16"
    assert body["resolution"] == "720p"
    assert body["generate_audio"] is True
    assert "audio_urls" not in plan.scenes[0].request_body
    ledger = {"operations": {}}
    ledger["operations"][plan.scenes[0].scene_id] = {"state": "SUCCEEDED"}
    assert next_unfinished_higgsfield_scene(ledger, plan) == plan.scenes[1].scene_id
    for scene in plan.scenes:
        ledger["operations"][scene.scene_id] = {"state": "SUCCEEDED"}
    assert next_unfinished_higgsfield_scene(ledger, plan) is None
    assert plan.reserved_usd <= SIMPLE_VIDEO_HARD_CAP_USD
    assert plan.cap_ok is True


def test_concat_and_zero_http_plan(tmp_path: Path) -> None:
    clips = []
    for index in range(2):
        path = tmp_path / f"s{index}.mp4"
        run_ffmpeg(
            [
                "-f",
                "lavfi",
                "-i",
                "color=c=orange:s=1080x1920:d=1:r=24",
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
    concat_simple_scenes(clips, tmp_path / "out.mp4")
    spec_path = Path(STORY_SPEC_RELATIVE)
    if not spec_path.is_file():
        pytest.skip("checked-in story spec not available")
    from docprod.product.story_pipeline import inspect_locked_character_refs

    refs = inspect_locked_character_refs()
    result = execute_higgsfield_scene_plan(refs=refs)
    assert result["provider_http_calls"] == 0
    assert result["execute"] is False
    assert result["scene_count"] == 8
    assert result["expected_usd"] == 8.64
    assert result["reserved_usd"] == 10.656
    assert result["new_image_usd"] == 0.0
    assert result["new_tts_usd"] == 0.0
    assert result["new_llm_usd"] == 0.0
    plan_body = result["plan"]
    assert isinstance(plan_body, dict)
    for scene in plan_body["scenes"]:
        assert scene["request_body"].get("generate_audio") is True
        assert "audio_urls" not in scene["request_body"]
        assert scene["external_tts"] is False
    assert result["higgsfield_credentials_present"] in {True, False}
    story = load_existing_story()
    assert story.title == "Sadece Su"
    with pytest.raises(PaidApiNotConfirmedError):
        execute_higgsfield_scene_generate(confirm_paid=False, refs=refs)
    dry = execute_higgsfield_scene_generate(
        confirm_paid=True,
        refs=refs,
        execute_calls=False,
        settings=_key_settings(),
    )
    assert dry["provider_http_calls"] == 0
    assert dry["plan"]["native_audio"] is True
    assert dry["plan"]["external_tts"] is False
    execute_higgsfield_scene_plan(refs=refs)


def _key_settings() -> Settings:
    from pydantic import SecretStr

    return Settings(
        allow_paid_apis=True,
        higgsfield_api_key_id=SecretStr("test-id"),
        higgsfield_api_key_secret=SecretStr("test-secret"),
        _env_file=None,
    )


def test_approved_plan_fingerprint_matches_locked_refs() -> None:
    spec_path = Path(STORY_SPEC_RELATIVE)
    if not spec_path.is_file():
        pytest.skip("checked-in story spec not available")
    from docprod.product.story_pipeline import inspect_locked_character_refs

    plan = build_higgsfield_scenes(load_existing_story(), inspect_locked_character_refs())
    assert higgsfield_plan_fingerprint(plan) == APPROVED_PLAN_FINGERPRINT


def test_live_auth_negative_cases(tmp_path: Path) -> None:
    spec_path = Path(STORY_SPEC_RELATIVE)
    if not spec_path.is_file():
        pytest.skip("checked-in story spec not available")
    from docprod.product.story_pipeline import inspect_locked_character_refs

    refs = inspect_locked_character_refs()
    plan = build_higgsfield_scenes(load_existing_story(), refs)
    keys = _key_settings()
    with pytest.raises(ProductError, match="series/episode is not birko episode 2"):
        assert_higgsfield_live_authorized(
            series_slug="birko",
            episode_number=3,
            stage="higgsfield-scene-generate",
            confirm_paid=True,
            plan=plan,
            settings=keys,
        )
    with pytest.raises(ProductError, match="HF_API_KEY is not present"):
        assert_higgsfield_live_authorized(
            series_slug="birko",
            episode_number=2,
            stage="higgsfield-scene-generate",
            confirm_paid=True,
            plan=plan,
            settings=Settings(allow_paid_apis=True, _env_file=None),
        )
    over = plan.model_copy(update={"reserved_usd": 12.01, "cap_ok": False})
    with pytest.raises(ProductError, match="reserved cost exceeds"):
        assert_higgsfield_live_authorized(
            series_slug="birko",
            episode_number=2,
            stage="higgsfield-scene-generate",
            confirm_paid=True,
            plan=over,
            settings=keys,
            approved_fingerprint=higgsfield_plan_fingerprint(over),
        )
    tmp_plan = build_higgsfield_scenes(_spec(), _refs(tmp_path), root=tmp_path)
    with pytest.raises(ProductError, match="plan fingerprint mismatch"):
        assert_higgsfield_live_authorized(
            series_slug="birko",
            episode_number=2,
            stage="higgsfield-scene-generate",
            confirm_paid=True,
            plan=tmp_plan,
            settings=keys,
        )


def test_generate_reaches_mocked_post(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec_path = Path(STORY_SPEC_RELATIVE)
    if not spec_path.is_file():
        pytest.skip("checked-in story spec not available")
    from docprod.product.story_pipeline import (
        inspect_locked_character_refs,
        run_friend_group_episode,
    )

    posted: list[dict[str, object]] = []

    def fake_submit(*, url: str, body: dict[str, object], confirm_paid: bool, settings=None):
        posted.append(body)
        assert "api.higgsfield.ai" in url
        return {"request_id": f"mock-{len(posted)}"}

    ledger = tmp_path / "ledger.json"

    def load_l(path):
        if ledger.is_file():
            return json.loads(ledger.read_text(encoding="utf-8"))
        return {"operations": {}}

    def save_l(path, payload):
        ledger.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    monkeypatch.setattr("docprod.product.higgsfield_scenes.submit_higgsfield_json", fake_submit)
    monkeypatch.setattr("docprod.product.higgsfield_scenes._load_ledger", load_l)
    monkeypatch.setattr("docprod.product.higgsfield_scenes._save_ledger", save_l)

    refs = inspect_locked_character_refs()
    keys = _key_settings()
    result = execute_higgsfield_scene_generate(
        confirm_paid=True,
        refs=refs,
        execute_calls=True,
        settings=keys,
        series_slug="birko",
        episode_number=2,
        submit=fake_submit,
    )
    assert result["live_post_authorized"] is True
    assert len(posted) == 8
    body = posted[0]
    assert body["generate_audio"] is True
    assert "audio_urls" not in body
    assert body["aspect_ratio"] == "9:16"
    assert body["resolution"] == "720p"

    with pytest.raises(PaidApiNotConfirmedError):
        run_friend_group_episode(
            stage="higgsfield-scene-generate",
            series_slug="birko",
            episode_number=2,
            confirm_paid=False,
            settings=keys,
            execute_calls=True,
        )
    posted.clear()
    if ledger.is_file():
        ledger.unlink()
    dispatched = run_friend_group_episode(
        stage="higgsfield-scene-generate",
        series_slug="birko",
        episode_number=2,
        confirm_paid=True,
        settings=keys,
        execute_calls=True,
    )
    assert dispatched["stage"] == "higgsfield-scene-generate"
    assert len(posted) == 8

    from typer.testing import CliRunner

    from docprod.cli import app

    posted.clear()
    if ledger.is_file():
        ledger.unlink()
    monkeypatch.setattr(
        "docprod.product.higgsfield_scenes.higgsfield_credentials_present",
        lambda settings=None: True,
    )
    cli = CliRunner().invoke(
        app,
        ["birko-episode2", "--stage", "higgsfield-scene-generate", "--confirm-paid"],
    )
    assert cli.exit_code == 0, cli.output
    assert "STOP BEFORE HTTP: Higgsfield scene payloads are planned" not in cli.output
    assert len(posted) == 8
    assert posted[0]["generate_audio"] is True
    assert "audio_urls" not in posted[0]


def test_preflight_zero_http() -> None:
    spec_path = Path(STORY_SPEC_RELATIVE)
    if not spec_path.is_file():
        pytest.skip("checked-in story spec not available")
    from docprod.product.story_pipeline import inspect_locked_character_refs

    keys = _key_settings()
    payload = execute_higgsfield_scene_preflight(
        refs=inspect_locked_character_refs(),
        settings=keys,
    )
    assert payload["provider_http_calls"] == 0
    assert payload["live_post_authorized"] is True
    assert payload["expected_usd"] == 8.64
    assert payload["reserved_usd"] == 10.656
    assert payload["hard_cap_usd"] == 12.0
    assert payload["ready_for_live"] is True
