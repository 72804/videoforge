from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image as PILImage

from docprod.config import Settings
from docprod.pipeline.produce_episode import _existing_keyframe
from docprod.providers.google_veo import (
    GoogleVeoProvider,
    combined_veo_prompt,
    load_local_start_image,
    start_image_mime,
)
from docprod.providers.paid_cache import PaidArtifactCache
from docprod.providers.video_base import VideoShotRequest
from docprod.storage.paths import ProjectPaths, default_projects_root

pytest.importorskip("google.genai")
from google.genai import types  # noqa: E402


def _write_image(path: Path, fmt: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "RGBA" if fmt == "WEBP" else "RGB"
    PILImage.new(mode, (32, 18), (12, 24, 36)).save(path, fmt)


def _request(path: Path) -> VideoShotRequest:
    return VideoShotRequest(
        prompt="Warehouse inspection. NO dialogue. NO narration.",
        negative_prompt="dialogue",
        image_path=path,
        native_audio_prompt="low warehouse room tone, restrained metal handling",
    )


def test_mime_mapping(tmp_path: Path) -> None:
    cases = {
        ".jpg": ("JPEG", "image/jpeg"),
        ".jpeg": ("JPEG", "image/jpeg"),
        ".png": ("PNG", "image/png"),
        ".webp": ("WEBP", "image/webp"),
    }
    for suffix, (fmt, mime) in cases.items():
        path = tmp_path / f"frame{suffix}"
        _write_image(path, fmt)
        assert start_image_mime(path) == mime
        image = load_local_start_image(path)
        assert isinstance(image, types.Image)
        assert image.image_bytes
        assert image.mime_type == mime
        assert str(image.mime_type).startswith("image/")


def test_unsupported_file_fails_before_client(tmp_path: Path) -> None:
    path = tmp_path / "notes.txt"
    path.write_text("not an image", encoding="utf-8")
    settings = Settings(_env_file=None, allow_paid_apis=True, gemini_api_key="unused")

    class Boom:
        def generate_videos(self, **_kwargs: object) -> None:
            raise AssertionError("network must not be called")

    provider = GoogleVeoProvider(
        settings=settings,
        client=SimpleNamespace(models=Boom(), files=SimpleNamespace()),
    )
    with pytest.raises(ValueError, match="Unsupported Veo start image"):
        provider.generate_shot(_request(path), confirm_paid=True)


def test_generate_videos_uses_source_image_not_file(tmp_path: Path) -> None:
    path = tmp_path / "start.jpg"
    _write_image(path, "JPEG")
    captured: dict[str, object] = {}

    class Models:
        def generate_videos(self, **kwargs: object) -> object:
            captured.update(kwargs)
            video = object()
            generated = SimpleNamespace(video=video)
            response = SimpleNamespace(generated_videos=[generated])
            return SimpleNamespace(done=True, response=response)

    class Files:
        def upload(self, **_kwargs: object) -> None:
            raise AssertionError("Files API must not be used for local start frames")

        def download(self, file: object, download_path: str) -> None:
            Path(download_path).write_bytes(b"fake-mp4")

    settings = Settings(
        _env_file=None,
        allow_paid_apis=True,
        gemini_api_key="unused",
        video_model="veo-3.1-lite-generate-preview",
    )
    provider = GoogleVeoProvider(
        settings=settings,
        client=SimpleNamespace(models=Models(), files=Files()),
        cache=PaidArtifactCache(tmp_path / "paid"),
    )
    result = provider.generate_shot(_request(path), confirm_paid=True)
    assert result.video_bytes == b"fake-mp4"
    assert captured["model"] == "veo-3.1-lite-generate-preview"
    assert "image" not in captured
    assert "prompt" not in captured
    source = captured["source"]
    assert isinstance(source, types.GenerateVideosSource)
    assert source.prompt
    assert "NO dialogue" in source.prompt
    assert "Native audio:" in source.prompt
    assert isinstance(source.image, types.Image)
    file_cls = getattr(types, "File", None)
    if file_cls is not None:
        assert not isinstance(source.image, file_cls)
    assert source.image.image_bytes
    assert str(source.image.mime_type).startswith("image/")
    dumped = source.model_dump(mode="python")
    image_dump = dumped["image"]
    assert image_dump["image_bytes"]
    assert image_dump["mime_type"].startswith("image/")
    aliased = source.model_dump(mode="python", by_alias=True)
    assert aliased["image"]["mimeType"].startswith("image/")
    assert aliased["image"]["imageBytes"]
    second = provider.generate_shot(_request(path), confirm_paid=True)
    assert second.metadata and second.metadata.get("cache_hit") == "true"


def test_existing_maple_keyframes_are_valid_jpegs() -> None:
    root = default_projects_root() / "maple_heist_canary"
    paths = ProjectPaths(root=root)
    for unit in ("au_0005_0006", "au_0025"):
        path = _existing_keyframe(paths, unit)
        image = PILImage.open(path)
        loaded = load_local_start_image(path)
        assert path.is_file()
        assert path.suffix.lower() == ".jpg"
        assert start_image_mime(path) == "image/jpeg"
        assert loaded.mime_type == "image/jpeg"
        assert isinstance(loaded, types.Image)
        assert loaded.image_bytes
        assert len(loaded.image_bytes) == path.stat().st_size
        assert image.size[0] > 0 and image.size[1] > 0


def test_combined_prompt_keeps_native_audio() -> None:
    req = _request(Path("unused.jpg"))
    text = combined_veo_prompt(req)
    assert req.prompt in text
    assert "Native audio:" in text
    assert "warehouse" in text
    assert "NO dialogue" in text
    assert "NO narration" in text
