from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from docprod.config import Settings
from docprod.product.friend_group import DialogueLineSpec, FriendGroupStorySpec
from docprod.product.higgsfield_scenes import (
    APPROVED_SCENE_IDS,
    HIGGSFIELD_LEDGER_RELATIVE,
    STORY_SPEC_RELATIVE,
    build_higgsfield_scenes,
    execute_higgsfield_scene_generate,
    execute_higgsfield_scene_resume,
    recover_higgsfield_jobs,
)
from docprod.render.ffmpeg import probe_media, run_ffmpeg

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


def _key_settings() -> Settings:
    from pydantic import SecretStr

    return Settings(
        allow_paid_apis=True,
        higgsfield_api_key_id=SecretStr("test-id"),
        higgsfield_api_key_secret=SecretStr("test-secret"),
        _env_file=None,
    )


def _write_vertical_mp4(path: Path, seconds: float = 0.5) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    run_ffmpeg(
        [
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=black:s=720x1280:d={seconds}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={seconds}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(path),
        ],
        timeout=30,
    )
    return path


def _submitted_ledger() -> dict[str, object]:
    return {
        "operations": {
            scene_id: {"state": "SUBMITTED", "request_id": f"req-{index}"}
            for index, scene_id in enumerate(APPROVED_SCENE_IDS, start=1)
        }
    }


def test_resume_polls_submitted_never_posts(tmp_path: Path) -> None:
    plan = build_higgsfield_scenes(_spec(), _refs(tmp_path), root=tmp_path)
    ledger_path = tmp_path / HIGGSFIELD_LEDGER_RELATIVE
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(json.dumps(_submitted_ledger()) + "\n", encoding="utf-8")
    posts: list[str] = []

    recovered = recover_higgsfield_jobs(
        plan,
        allow_submit=False,
        submit=lambda **kwargs: posts.append("post") or {"request_id": "x"},
        status_fn=lambda request_id, settings=None: {"status": "in_progress"},
        result_fn=lambda request_id, settings=None: {},
        download_fn=lambda url, dest: dest,
        sleeper=lambda _delay: None,
        now_fn=lambda: 0.0,
        deadline_seconds=0.0,
        root=tmp_path,
    )
    assert posts == []
    assert recovered["generation_posts"] == 0
    saved = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert saved["operations"]["HF1_hook_bill"]["request_id"] == "req-1"
    assert saved["operations"]["HF1_hook_bill"]["state"] == "SUBMITTED"


def test_completed_request_downloads_and_concat_keeps_audio(tmp_path: Path) -> None:
    plan = build_higgsfield_scenes(_spec(), _refs(tmp_path), root=tmp_path)
    ledger_path = tmp_path / HIGGSFIELD_LEDGER_RELATIVE
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ops = _submitted_ledger()["operations"]
    assert isinstance(ops, dict)
    ops["HF2_order_setup"]["state"] = "PROCESSING"
    ledger_path.write_text(json.dumps({"operations": ops}) + "\n", encoding="utf-8")
    downloaded: list[str] = []

    recovered = recover_higgsfield_jobs(
        plan,
        allow_submit=False,
        submit=lambda **kwargs: (_ for _ in ()).throw(AssertionError("posted")),
        status_fn=lambda request_id, settings=None: {"status": "completed"},
        result_fn=lambda request_id, settings=None: {
            "video": {"url": f"https://example.test/{request_id}.mp4"}
        },
        download_fn=lambda url, dest: downloaded.append(url) or _write_vertical_mp4(Path(dest)),
        sleeper=lambda _delay: None,
        now_fn=lambda: 0.0,
        deadline_seconds=1_000.0,
        root=tmp_path,
    )
    assert recovered["generation_posts"] == 0
    assert len(downloaded) == 8
    saved = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert saved["operations"]["HF1_hook_bill"]["state"] == "SUCCEEDED"
    assert saved["operations"]["HF1_hook_bill"]["downloaded"] is True
    assert saved["operations"]["HF1_hook_bill"]["audio_present"] is True
    assert recovered["final"]
    info = probe_media(Path(str(recovered["final"])))
    assert info.has_audio
    assert info.has_video


def test_processing_keeps_same_id(tmp_path: Path) -> None:
    plan = build_higgsfield_scenes(_spec(), _refs(tmp_path), root=tmp_path)
    ledger_path = tmp_path / HIGGSFIELD_LEDGER_RELATIVE
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(json.dumps(_submitted_ledger()) + "\n", encoding="utf-8")
    ticks = {"n": 0}

    def now_fn() -> float:
        ticks["n"] += 1
        if ticks["n"] <= 2:
            return 0.0
        return 10.0

    recovered = recover_higgsfield_jobs(
        plan,
        allow_submit=False,
        status_fn=lambda request_id, settings=None: {"status": "processing"},
        result_fn=lambda request_id, settings=None: {},
        download_fn=lambda url, dest: dest,
        sleeper=lambda _delay: None,
        now_fn=now_fn,
        deadline_seconds=5.0,
        root=tmp_path,
    )
    saved = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert saved["operations"]["HF1_hook_bill"]["request_id"] == "req-1"
    assert saved["operations"]["HF1_hook_bill"]["state"] == "PROCESSING"
    assert recovered["generation_posts"] == 0
    assert recovered["final"] is None


def test_failed_request_is_not_retried(tmp_path: Path) -> None:
    plan = build_higgsfield_scenes(_spec(), _refs(tmp_path), root=tmp_path)
    ledger_path = tmp_path / HIGGSFIELD_LEDGER_RELATIVE
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(json.dumps(_submitted_ledger()) + "\n", encoding="utf-8")
    recovered = recover_higgsfield_jobs(
        plan,
        allow_submit=True,
        confirm_paid=True,
        submit=lambda **kwargs: (_ for _ in ()).throw(AssertionError("posted")),
        status_fn=lambda request_id, settings=None: {
            "status": "failed",
            "error": "provider boom",
        },
        result_fn=lambda request_id, settings=None: {},
        download_fn=lambda url, dest: dest,
        sleeper=lambda _delay: None,
        now_fn=lambda: 0.0,
        deadline_seconds=1_000.0,
        root=tmp_path,
    )
    saved = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert saved["operations"]["HF1_hook_bill"]["state"] == "FAILED"
    assert "boom" in str(saved["operations"]["HF1_hook_bill"].get("error"))
    assert recovered["generation_posts"] == 0


def test_uncertain_never_resubmits(tmp_path: Path) -> None:
    plan = build_higgsfield_scenes(_spec(), _refs(tmp_path), root=tmp_path)
    ledger_path = tmp_path / HIGGSFIELD_LEDGER_RELATIVE
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    payload = _submitted_ledger()
    ops = payload["operations"]
    assert isinstance(ops, dict)
    ops["HF1_hook_bill"]["state"] = "UNCERTAIN"
    ledger_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    recovered = recover_higgsfield_jobs(
        plan,
        allow_submit=True,
        confirm_paid=True,
        submit=lambda **kwargs: (_ for _ in ()).throw(AssertionError("posted")),
        status_fn=lambda request_id, settings=None: {"status": "queued"},
        result_fn=lambda request_id, settings=None: {},
        download_fn=lambda url, dest: dest,
        sleeper=lambda _delay: None,
        now_fn=lambda: 0.0,
        deadline_seconds=0.0,
        root=tmp_path,
    )
    saved = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert saved["operations"]["HF1_hook_bill"]["state"] == "UNCERTAIN"
    assert recovered["generation_posts"] == 0


def test_partial_completion_persists(tmp_path: Path) -> None:
    plan = build_higgsfield_scenes(_spec(), _refs(tmp_path), root=tmp_path)
    ledger_path = tmp_path / HIGGSFIELD_LEDGER_RELATIVE
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(json.dumps(_submitted_ledger()) + "\n", encoding="utf-8")

    def status_fn(request_id: str, *, settings=None):
        if request_id == "req-1":
            return {"status": "completed"}
        return {"status": "processing"}

    steps = {"n": 0}

    def now_fn() -> float:
        steps["n"] += 1
        return 0.0 if steps["n"] < 8 else 10_000.0

    recover_higgsfield_jobs(
        plan,
        allow_submit=False,
        status_fn=status_fn,
        result_fn=lambda request_id, settings=None: {
            "video": {"url": "https://example.test/one.mp4"}
        },
        download_fn=lambda url, dest: _write_vertical_mp4(Path(dest)),
        sleeper=lambda _delay: None,
        now_fn=now_fn,
        deadline_seconds=1_000.0,
        root=tmp_path,
    )
    saved = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert saved["operations"]["HF1_hook_bill"]["state"] == "SUCCEEDED"
    assert saved["operations"]["HF2_order_setup"]["request_id"] == "req-2"
    assert saved["operations"]["HF2_order_setup"]["state"] in {"SUBMITTED", "PROCESSING"}


def test_resume_stage_zero_generation_posts(tmp_path: Path) -> None:
    spec_path = Path(STORY_SPEC_RELATIVE)
    if not spec_path.is_file():
        pytest.skip("checked-in story spec not available")
    from docprod.product.story_pipeline import inspect_locked_character_refs

    ledger_path = tmp_path / HIGGSFIELD_LEDGER_RELATIVE
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(json.dumps(_submitted_ledger()) + "\n", encoding="utf-8")
    result = execute_higgsfield_scene_resume(
        refs=inspect_locked_character_refs(),
        status_fn=lambda request_id, settings=None: {"status": "queued"},
        result_fn=lambda request_id, settings=None: {},
        download_fn=lambda url, dest: dest,
        sleeper=lambda _delay: None,
        now_fn=lambda: 0.0,
        deadline_seconds=0.0,
        root=tmp_path,
    )
    assert result["generation_posts"] == 0
    assert result["stage"] == "higgsfield-scene-resume"


def test_generate_resumes_submitted_jobs(tmp_path: Path) -> None:
    spec_path = Path(STORY_SPEC_RELATIVE)
    if not spec_path.is_file():
        pytest.skip("checked-in story spec not available")
    from docprod.product.story_pipeline import inspect_locked_character_refs

    ledger_path = tmp_path / HIGGSFIELD_LEDGER_RELATIVE
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(json.dumps(_submitted_ledger()) + "\n", encoding="utf-8")
    posts: list[str] = []
    result = execute_higgsfield_scene_generate(
        confirm_paid=True,
        refs=inspect_locked_character_refs(),
        execute_calls=True,
        settings=_key_settings(),
        submit=lambda **kwargs: posts.append("post") or {"request_id": "new"},
        status_fn=lambda request_id, settings=None: {"status": "processing"},
        result_fn=lambda request_id, settings=None: {},
        download_fn=lambda url, dest: dest,
        sleeper=lambda _delay: None,
        now_fn=lambda: 0.0,
        deadline_seconds=0.0,
        root=tmp_path,
    )
    assert posts == []
    assert result["generation_posts"] == 0
    assert result["states"]["HF1_hook_bill"] == "SUBMITTED"
