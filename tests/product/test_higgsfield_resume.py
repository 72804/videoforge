from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from docprod.config import Settings
from docprod.product.friend_group import DialogueLineSpec, FriendGroupStorySpec
from docprod.product.higgsfield_scenes import (
    APPROVED_SCENE_IDS,
    HF3_REVISION_2_VIDEO_PROMPT,
    HF3_REVISION_3_PROMPT,
    HIGGSFIELD_LEDGER_RELATIVE,
    ORIGINAL_HF3_VIDEO_PROMPT,
    ORIGINAL_HF4_VIDEO_PROMPT,
    STORY_SPEC_RELATIVE,
    build_higgsfield_scenes,
    execute_higgsfield_scene_generate,
    execute_higgsfield_scene_resume,
    parse_only_scenes,
    recover_higgsfield_jobs,
    selected_scene_cost_report,
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
        url_probe=lambda url: {
            "status_code": 200,
            "ok": True,
            "bytes": 64,
            "content_type": "image/jpeg",
        },
    )
    assert posts == []
    assert result["generation_posts"] == 0
    assert result["states"]["HF1_hook_bill"] == "SUBMITTED"


def test_failed_requires_explicit_retry_and_preserves_old_ids(tmp_path: Path) -> None:
    plan = build_higgsfield_scenes(_spec(), _refs(tmp_path), root=tmp_path)
    ledger_path = tmp_path / HIGGSFIELD_LEDGER_RELATIVE
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    payload = _submitted_ledger()
    ops = payload["operations"]
    assert isinstance(ops, dict)
    ops["HF1_hook_bill"] = {
        "state": "FAILED",
        "request_id": "old-failed-1",
        "error": "public URL required",
    }
    ledger_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    posts: list[str] = []
    recover_higgsfield_jobs(
        plan,
        allow_submit=True,
        retry_failed=False,
        confirm_paid=True,
        submit=lambda **kwargs: posts.append("post") or {"request_id": "new"},
        status_fn=lambda request_id, settings=None: {"status": "queued"},
        sleeper=lambda _delay: None,
        now_fn=lambda: 0.0,
        deadline_seconds=0.0,
        root=tmp_path,
    )
    assert posts == []
    saved = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert saved["operations"]["HF1_hook_bill"]["request_id"] == "old-failed-1"
    recovered = recover_higgsfield_jobs(
        plan,
        allow_submit=True,
        retry_failed=True,
        confirm_paid=True,
        submit=lambda **kwargs: {"request_id": "brand-new"},
        status_fn=lambda request_id, settings=None: {"status": "queued"},
        sleeper=lambda _delay: None,
        now_fn=lambda: 0.0,
        deadline_seconds=0.0,
        root=tmp_path,
    )
    saved = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert recovered["generation_posts"] >= 1
    assert saved["operations"]["HF1_hook_bill"]["request_id"] == "brand-new"
    assert "old-failed-1" in saved["operations"]["HF1_hook_bill"]["failed_request_ids"]


def test_completed_status_video_url_skips_result_fn(tmp_path: Path) -> None:
    plan = build_higgsfield_scenes(_spec(), _refs(tmp_path), root=tmp_path)
    ledger_path = tmp_path / HIGGSFIELD_LEDGER_RELATIVE
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    payload = _submitted_ledger()
    ops = payload["operations"]
    assert isinstance(ops, dict)
    for scene_id in list(ops)[1:]:
        ops[scene_id] = {
            "state": "FAILED",
            "request_id": f"old-{scene_id}",
            "error": "Please provide a publicly accessible HTTP or HTTPS URL for the input file.",
        }
    ops["HF1_hook_bill"] = {
        "state": "PROCESSING",
        "request_id": "3668993e-89df-4678-9dba-56a13c53987b",
        "history": [{"state": "FAILED", "request_id": "d0599681-5173-4954-93e6-080fc6da67c3"}],
        "failed_request_ids": ["d0599681-5173-4954-93e6-080fc6da67c3"],
    }
    ledger_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    result_calls: list[str] = []
    recovered = recover_higgsfield_jobs(
        plan,
        allow_submit=True,
        confirm_paid=True,
        submit=lambda **kwargs: (_ for _ in ()).throw(AssertionError("posted")),
        status_fn=lambda request_id, settings=None: {
            "status": "completed",
            "request_id": request_id,
            "status_url": f"https://api.higgsfield.ai/requests/{request_id}/status",
            "video": {"url": "https://cdn.example/clip.mp4"},
        },
        result_fn=lambda request_id, settings=None: result_calls.append(request_id) or {},
        download_fn=lambda url, dest: _write_vertical_mp4(Path(dest)),
        sleeper=lambda _delay: None,
        now_fn=lambda: 0.0,
        deadline_seconds=1_000.0,
        root=tmp_path,
    )
    saved = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert recovered["generation_posts"] == 0
    assert result_calls == []
    assert saved["operations"]["HF1_hook_bill"]["state"] == "SUCCEEDED"
    assert saved["operations"]["HF1_hook_bill"]["request_id"] == (
        "3668993e-89df-4678-9dba-56a13c53987b"
    )
    assert saved["operations"]["HF1_hook_bill"]["audio_present"] is True
    assert "d0599681-5173-4954-93e6-080fc6da67c3" in saved["operations"]["HF1_hook_bill"][
        "failed_request_ids"
    ]
    assert saved["operations"]["HF2_order_setup"]["request_id"] == "old-HF2_order_setup"
    assert saved["operations"]["HF2_order_setup"]["state"] == "FAILED"


def test_completed_status_response_url_uses_exact_url(tmp_path: Path) -> None:
    plan = build_higgsfield_scenes(_spec(), _refs(tmp_path), root=tmp_path)
    ledger_path = tmp_path / HIGGSFIELD_LEDGER_RELATIVE
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(json.dumps(_submitted_ledger()) + "\n", encoding="utf-8")
    seen: list[dict[str, object]] = []

    def result_fn(request_id: str, *, settings=None, payload=None):
        seen.append({"request_id": request_id, "payload": payload})
        assert payload is not None
        assert payload["response_url"] == "https://api.higgsfield.ai/exact-result"
        return {"video": {"url": "https://cdn.example/from-response.mp4"}}

    recover_higgsfield_jobs(
        plan,
        allow_submit=False,
        status_fn=lambda request_id, settings=None: {
            "status": "completed",
            "response_url": "https://api.higgsfield.ai/exact-result",
        },
        result_fn=result_fn,
        download_fn=lambda url, dest: _write_vertical_mp4(Path(dest)),
        sleeper=lambda _delay: None,
        now_fn=lambda: 0.0,
        deadline_seconds=1_000.0,
        root=tmp_path,
    )
    assert seen
    assert seen[0]["payload"]["response_url"] == "https://api.higgsfield.ai/exact-result"


def test_result_http_405_does_not_resubmit(tmp_path: Path) -> None:
    import httpx

    plan = build_higgsfield_scenes(_spec(), _refs(tmp_path), root=tmp_path)
    ledger_path = tmp_path / HIGGSFIELD_LEDGER_RELATIVE
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(json.dumps(_submitted_ledger()) + "\n", encoding="utf-8")
    posts: list[str] = []

    def result_fn(request_id: str, *, settings=None, payload=None):
        request = httpx.Request("GET", f"https://api.higgsfield.ai/requests/{request_id}")
        response = httpx.Response(405, request=request)
        raise httpx.HTTPStatusError("Method Not Allowed", request=request, response=response)

    recovered = recover_higgsfield_jobs(
        plan,
        allow_submit=True,
        retry_failed=True,
        confirm_paid=True,
        submit=lambda **kwargs: posts.append("post") or {"request_id": "replacement"},
        status_fn=lambda request_id, settings=None: {"status": "completed"},
        result_fn=result_fn,
        download_fn=lambda url, dest: dest,
        sleeper=lambda _delay: None,
        now_fn=lambda: 0.0,
        deadline_seconds=1_000.0,
        root=tmp_path,
    )
    saved = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert posts == []
    assert recovered["generation_posts"] == 0
    assert saved["operations"]["HF1_hook_bill"]["state"] == "UNCERTAIN"
    assert saved["operations"]["HF1_hook_bill"]["request_id"] == "req-1"


def _current_style_ledger() -> dict[str, object]:
    succeeded = {"HF1_hook_bill", "HF2_order_setup", "HF5_erni", "HF6_musti"}
    ops: dict[str, object] = {}
    for index, scene_id in enumerate(APPROVED_SCENE_IDS, start=1):
        if scene_id in succeeded:
            ops[scene_id] = {"state": "SUCCEEDED", "request_id": f"ok-{index}"}
        elif scene_id == "HF3_birko_slips":
            ops[scene_id] = {
                "state": "FAILED",
                "request_id": "7debbdd7-7bc1-452e-9b64-3576d47f8c10",
                "error": (
                    "The generated result was blocked by content safety checks. "
                    "Try a different prompt or reference media."
                ),
            }
        elif scene_id == "HF4_muge_kemal":
            ops[scene_id] = {
                "state": "FAILED",
                "request_id": "ac583921-462b-4617-a814-0a69acb5f376",
                "provider_status": "nsfw",
                "error": "nsfw",
            }
        else:
            ops[scene_id] = {
                "state": "FAILED",
                "request_id": f"old-{scene_id}",
                "error": (
                    "Please provide a publicly accessible HTTP or HTTPS URL "
                    "for the input file."
                ),
            }
    return {"operations": ops}


def _write_succeeded_clips(tmp_path: Path) -> None:
    from docprod.product.higgsfield_scenes import _clip_path

    for scene_id in ("HF1_hook_bill", "HF2_order_setup", "HF5_erni", "HF6_musti"):
        _write_vertical_mp4(_clip_path(scene_id, root=tmp_path))


def test_only_hf7_hf8_submit_two_posts(tmp_path: Path) -> None:
    plan = build_higgsfield_scenes(_spec(), _refs(tmp_path), root=tmp_path)
    ledger_path = tmp_path / HIGGSFIELD_LEDGER_RELATIVE
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(json.dumps(_current_style_ledger()) + "\n", encoding="utf-8")
    _write_succeeded_clips(tmp_path)
    posts: list[str] = []

    def submit(**kwargs):
        body = kwargs["body"]
        posts.append(str(kwargs["url"]))
        assert "audio_urls" not in body
        assert body.get("generate_audio") is True
        return {"request_id": f"new-{len(posts)}"}

    recovered = recover_higgsfield_jobs(
        plan,
        allow_submit=True,
        retry_failed=True,
        confirm_paid=True,
        only_scenes=parse_only_scenes("HF7_kemal_pays,HF8_payoff"),
        submit=submit,
        status_fn=lambda request_id, settings=None: {"status": "queued"},
        sleeper=lambda _delay: None,
        now_fn=lambda: 0.0,
        deadline_seconds=0.0,
        root=tmp_path,
    )
    saved = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert recovered["generation_posts"] == 2
    assert len(posts) == 2
    assert recovered["selected_expected_total"] == 2.016
    assert recovered["selected_generation_posts_max"] == 2
    assert saved["operations"]["HF1_hook_bill"]["request_id"] == "ok-1"
    assert saved["operations"]["HF3_birko_slips"]["request_id"] == (
        "7debbdd7-7bc1-452e-9b64-3576d47f8c10"
    )
    assert saved["operations"]["HF4_muge_kemal"]["request_id"] == (
        "ac583921-462b-4617-a814-0a69acb5f376"
    )
    assert saved["operations"]["HF7_kemal_pays"]["request_id"] == "new-1"
    assert saved["operations"]["HF8_payoff"]["request_id"] == "new-2"
    assert "old-HF7_kemal_pays" in saved["operations"]["HF7_kemal_pays"]["failed_request_ids"]
    hf7 = next(scene for scene in plan.scenes if scene.scene_id == "HF7_kemal_pays")
    hf8 = next(scene for scene in plan.scenes if scene.scene_id == "HF8_payoff")
    assert hf7.model == "seedance-2.5-image-to-video"
    assert hf8.model == "seedance-2.5-image-to-video"
    assert hf7.native_audio is True
    assert plan.hard_cap_usd == 12.0


def test_safety_failures_not_retried_without_only_scenes(tmp_path: Path) -> None:
    plan = build_higgsfield_scenes(_spec(), _refs(tmp_path), root=tmp_path)
    ledger_path = tmp_path / HIGGSFIELD_LEDGER_RELATIVE
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(json.dumps(_current_style_ledger()) + "\n", encoding="utf-8")
    _write_succeeded_clips(tmp_path)
    posts: list[str] = []
    recover_higgsfield_jobs(
        plan,
        allow_submit=True,
        retry_failed=True,
        confirm_paid=True,
        submit=lambda **kwargs: posts.append(kwargs["url"]) or {"request_id": f"n{len(posts)}"},
        status_fn=lambda request_id, settings=None: {"status": "queued"},
        sleeper=lambda _delay: None,
        now_fn=lambda: 0.0,
        deadline_seconds=0.0,
        root=tmp_path,
    )
    saved = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert len(posts) == 2
    assert saved["operations"]["HF3_birko_slips"]["request_id"] == (
        "7debbdd7-7bc1-452e-9b64-3576d47f8c10"
    )
    assert saved["operations"]["HF4_muge_kemal"]["error"] == "nsfw"


def test_one_scene_hf3_retry_leaves_hf4(tmp_path: Path) -> None:
    plan = build_higgsfield_scenes(_spec(), _refs(tmp_path), root=tmp_path)
    ledger_path = tmp_path / HIGGSFIELD_LEDGER_RELATIVE
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(json.dumps(_current_style_ledger()) + "\n", encoding="utf-8")
    _write_succeeded_clips(tmp_path)
    posts: list[str] = []
    recover_higgsfield_jobs(
        plan,
        allow_submit=True,
        retry_failed=True,
        confirm_paid=True,
        only_scenes=parse_only_scenes("HF3_birko_slips"),
        submit=lambda **kwargs: posts.append(kwargs.get("url", "p")) or {"request_id": "hf3-new"},
        status_fn=lambda request_id, settings=None: {"status": "queued"},
        sleeper=lambda _delay: None,
        now_fn=lambda: 0.0,
        deadline_seconds=0.0,
        root=tmp_path,
    )
    saved = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert len(posts) == 1
    assert str(posts[0]).endswith("image-to-video")
    assert saved["operations"]["HF3_birko_slips"]["request_id"] == "hf3-new"
    assert saved["operations"]["HF3_birko_slips"]["prompt_revision"] == 3
    assert saved["operations"]["HF3_birko_slips"]["prompt_history"][0]["prompt"] == (
        ORIGINAL_HF3_VIDEO_PROMPT
    )
    assert saved["operations"]["HF3_birko_slips"]["prompt_history"][1]["prompt"] == (
        HF3_REVISION_2_VIDEO_PROMPT
    )
    assert saved["operations"]["HF4_muge_kemal"]["request_id"] == (
        "ac583921-462b-4617-a814-0a69acb5f376"
    )


def test_sanitized_prompts_preserve_history_and_drop_bible(tmp_path: Path) -> None:
    plan = build_higgsfield_scenes(_spec(), _refs(tmp_path), root=tmp_path)
    hf3 = next(scene for scene in plan.scenes if scene.scene_id == "HF3_birko_slips")
    hf4 = next(scene for scene in plan.scenes if scene.scene_id == "HF4_muge_kemal")
    hf7 = next(scene for scene in plan.scenes if scene.scene_id == "HF7_kemal_pays")
    assert hf3.prompt_revision == 3
    assert hf3.prompt_revision_reason == "Birko-only I2V safety fallback"
    assert hf3.model == "seedance-2.5-image-to-video"
    assert hf3.visible_characters == ["birko"]
    assert len(hf3.input_assets) == 1
    assert hf3.input_assets[0]["key"] == "birko"
    assert hf3.video_prompt == HF3_REVISION_3_PROMPT
    assert hf3.expected_usd == 0.864
    assert "image_url" in hf3.request_body
    assert "image_urls" not in hf3.request_body
    assert hf3.request_body["generate_audio"] is True
    assert "audio_urls" not in hf3.request_body
    assert hf4.prompt_revision == 2
    assert hf3.prompt_history[0]["prompt"] == ORIGINAL_HF3_VIDEO_PROMPT
    assert hf3.prompt_history[1]["prompt"] == HF3_REVISION_2_VIDEO_PROMPT
    assert hf4.prompt_history[0]["prompt"] == ORIGINAL_HF4_VIDEO_PROMPT
    assert "No sexual content" not in hf3.video_prompt
    assert "No nudity" not in hf3.video_prompt
    assert "No violence" not in hf3.video_prompt
    assert "Character bible" not in hf3.video_prompt
    assert "slips out" not in hf3.video_prompt
    assert " HG" not in hf3.video_prompt
    assert "flörtöz" not in hf4.video_prompt
    assert "flirtatious" not in hf4.video_prompt.casefold()
    assert "Character bible" not in hf4.video_prompt
    assert "grabs the receipt" not in hf4.video_prompt
    assert "slips out" not in hf3.video_prompt
    assert "leans in" not in hf3.video_prompt
    assert "Bu özel kutuyu kim söyledi?" in hf4.video_prompt
    assert "Kocan kaçmış, sen kutuyu soruyorsun!" in hf4.video_prompt
    assert "Fiyatını gördün mü?" in hf4.video_prompt
    assert hf3.native_audio is True
    assert "audio_urls" not in hf7.request_body
    assert hf7.prompt_revision == 1
    costs = selected_scene_cost_report(
        plan, parse_only_scenes("HF7_kemal_pays,HF8_payoff")
    )
    assert costs["selected_expected_total"] == 2.016
    assert costs["selected_generation_posts_max"] == 2
    hf3_cost = selected_scene_cost_report(plan, parse_only_scenes("HF3_birko_slips"))
    assert hf3_cost["selected_expected_total"] == 0.864
    assert hf3_cost["selected_generation_posts_max"] == 1
