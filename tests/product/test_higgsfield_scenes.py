from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from docprod.exceptions import PaidApiNotConfirmedError
from docprod.product.errors import ProductError
from docprod.product.friend_group import DialogueLineSpec, FriendGroupStorySpec
from docprod.product.higgsfield_scenes import (
    SIMPLE_VIDEO_HARD_CAP_USD,
    STORY_SPEC_RELATIVE,
    build_higgsfield_scenes,
    execute_higgsfield_scene_generate,
    execute_higgsfield_scene_plan,
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


def test_no_astra_in_higgsfield_plan_path() -> None:
    import inspect

    from docprod.product import higgsfield_scenes as module

    source = inspect.getsource(module)
    assert "simple-script-generate" not in source
    assert "OpenAIStoryClient" not in source
    assert "gpt-6-astra" not in source


def test_visible_cast_and_unique_refs(tmp_path: Path) -> None:
    plan = build_higgsfield_scenes(_spec(), _refs(tmp_path), root=tmp_path)
    for scene in plan.scenes:
        assert 1 <= len(scene.visible_characters) <= 3
        assert len(scene.character_refs) == len(set(scene.character_refs))
        assert len(scene.character_refs) == len(scene.visible_characters)
        assert "zoompan" not in scene.video_prompt
        assert 5 <= scene.duration <= 10
        assert scene.model == "seedance-2.5-reference-to-video"


def test_seedance_construction_and_resume(tmp_path: Path) -> None:
    plan = build_higgsfield_scenes(_spec(), _refs(tmp_path), root=tmp_path)
    body = seedance_reference_to_video_body(
        prompt=plan.scenes[0].video_prompt,
        duration=plan.scenes[0].duration,
        image_urls=plan.scenes[0].request_body["image_urls"],
    )
    assert body["aspect_ratio"] == "9:16"
    assert body["resolution"] == "720p"
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
    story = load_existing_story()
    assert story.title == "Sadece Su"
    with pytest.raises(PaidApiNotConfirmedError):
        execute_higgsfield_scene_generate(confirm_paid=False, refs=refs)
    dry = execute_higgsfield_scene_generate(
        confirm_paid=True, refs=refs, execute_calls=False
    )
    assert dry["provider_http_calls"] == 0
    with pytest.raises(ProductError, match="STOP BEFORE HTTP"):
        execute_higgsfield_scene_generate(confirm_paid=True, refs=refs, execute_calls=True)
