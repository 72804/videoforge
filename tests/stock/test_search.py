from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from tests.render.helpers import mini_plan
from tests.stock.helpers import (
    TEST_KEY,
    FakeTransport,
    settings_with_key,
    stock_plan,
    stock_scene,
    video_payload,
)

from docprod.exceptions import StockProviderError
from docprod.models.project import Project
from docprod.pipeline.search_stock import search_stock, select_stock
from docprod.render.ffmpeg import probe_media, run_ffmpeg
from docprod.render.models import TINY_TEST_PROFILE
from docprod.render.renderer import render_preview
from docprod.render.still import resolve_scene_visual
from docprod.stock.models import StockCreditsManifest, StockSearchManifest
from docprod.stock.pexels import PexelsStockVideoProvider
from docprod.storage.hashing import file_sha256
from docprod.storage.json_store import load_model
from docprod.storage.paths import ProjectPaths


def _project() -> Project:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return Project(
        id="tiny",
        title="Tiny",
        language="tr",
        target_duration_seconds=2,
        created_at=now,
        updated_at=now,
        random_seed=7,
    )


def _color_mp4(
    path: Path, *, duration: float = 3.0, width: int = 1920, height: int = 1080
) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=size={width}x{height}:rate=30",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=44100",
            "-t",
            str(duration),
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            str(path),
        ],
        timeout=60,
    )
    return path.read_bytes()


def test_search_dedupes_and_writes_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = ProjectPaths(root=tmp_path / "proj")
    videos = [video_payload(101), video_payload(101, slug="railway-station"), video_payload(102)]
    transport = FakeTransport(videos=videos)
    provider = PexelsStockVideoProvider(
        settings=settings_with_key(monkeypatch), transport=transport
    )
    scene = stock_scene(
        "scene_0001",
        "İstanbul'daki tren istasyonu akşam saatlerinde neredeyse boştu.",
        duration=1.0,
    )
    manifest = search_stock(
        paths,
        project=_project(),
        plan=stock_plan(scene),
        provider=provider,
    )
    assert manifest.search_url.endswith("/v1/videos/search")
    ids = [item.provider_video_id for item in manifest.scenes[0].candidates]
    assert ids.count("101") == 1
    assert set(ids) == {"101", "102"}
    json_path = paths.stock_candidates_json()
    assert json_path.is_file()
    text = json_path.read_text(encoding="utf-8")
    assert TEST_KEY not in text
    assert "Authorization" not in text
    loaded = load_model(json_path, StockSearchManifest)
    assert loaded.scenes[0].contact_sheet
    sheet = Path(loaded.scenes[0].contact_sheet or "")
    assert sheet.is_file()
    assert sheet.name == "scene_0001_candidates.jpg"


def test_select_downloads_hashes_normalizes_and_credits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = ProjectPaths(root=tmp_path / "proj")
    paths.preview_segments_dir.mkdir(parents=True, exist_ok=True)
    source = tmp_path / "src.mp4"
    payload = _color_mp4(source, duration=3.0)
    transport = FakeTransport(videos=[video_payload(101)], mp4_bytes=payload)
    provider = PexelsStockVideoProvider(
        settings=settings_with_key(monkeypatch), transport=transport
    )
    scene = stock_scene(
        "scene_0001",
        "İstanbul'daki tren istasyonu akşam saatlerinde neredeyse boştu.",
        duration=0.4,
    )
    search_stock(paths, project=_project(), plan=stock_plan(scene), provider=provider)
    meta = select_stock(
        paths,
        project=_project(),
        plan=stock_plan(scene),
        scene_id="scene_0001",
        video_id="101",
        provider=provider,
    )
    source_mp4 = paths.stock_source_mp4("scene_0001")
    assert source_mp4.is_file()
    assert meta.sha256 == file_sha256(source_mp4)
    assert meta.selected_rendition["width"] == 1920
    assert meta.creator_name == "Jane Doe"
    assert "pexels.com/video" in meta.source_page_url
    clip = paths.stock_clip_mp4("scene_0001")
    probe = probe_media(clip)
    assert probe.width == 1280
    assert probe.height == 720
    assert probe.pixel_format == "yuv420p"
    assert probe.has_audio is False
    assert abs((probe.fps or 0) - 30) < 0.1
    credits = load_model(paths.stock_credits_json(), StockCreditsManifest)
    assert credits.sources[0].scene_id == "scene_0001"
    assert credits.sources[0].creator == "Jane Doe"
    txt = paths.stock_credits_txt().read_text(encoding="utf-8")
    assert "Jane Doe" in txt
    visual = resolve_scene_visual(paths, scene)
    assert visual is not None
    assert visual.kind == "stock_video"
    result = render_preview(
        paths,
        project=_project(),
        plan=mini_plan(scene),
        profile=TINY_TEST_PROFILE,
        workers=1,
        use_cache=False,
    )
    record = result.manifest.segments[0]
    assert record.source_asset == "stock_video"
    assert record.effect_rendered.value == "none"
    assert record.effect_override_reason == "native_video_motion"
    assert "placeholder" not in record.ffmpeg_command_summary
    assert "stock-video" in record.ffmpeg_command_summary
    out = probe_media(paths.preview_segments_dir / "scene_0001.mp4")
    assert out.has_audio is False
    assert out.width == TINY_TEST_PROFILE.width
    assert out.height == TINY_TEST_PROFILE.height


def test_too_short_source_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = ProjectPaths(root=tmp_path / "proj")
    source = tmp_path / "short.mp4"
    payload = _color_mp4(source, duration=0.5)
    videos = [video_payload(101, duration=0.5)]
    transport = FakeTransport(videos=videos, mp4_bytes=payload)
    provider = PexelsStockVideoProvider(
        settings=settings_with_key(monkeypatch), transport=transport
    )
    scene = stock_scene("scene_0001", "tren istasyonu boştu", duration=2.0)
    search_stock(paths, project=_project(), plan=stock_plan(scene), provider=provider)
    with pytest.raises(StockProviderError, match="too short"):
        select_stock(
            paths,
            project=_project(),
            plan=stock_plan(scene),
            scene_id="scene_0001",
            video_id="101",
            provider=provider,
        )


def test_cover_crop_has_no_stretch() -> None:
    from docprod.render.still import still_fit_filter

    filt = still_fit_filter(1920, 800, 1280, 720)
    assert "force_original_aspect_ratio=increase" in filt
    assert "crop=1280:720" in filt
    assert "setsar" not in filt
