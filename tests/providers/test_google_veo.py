from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image as PILImage

from docprod.config import Settings
from docprod.pipeline.produce_episode import SHOTS, _existing_keyframe, _shot_request
from docprod.providers.google_veo import (
    GoogleVeoProvider,
    build_veo_prompt,
    combined_veo_prompt,
    constraint_items,
    load_local_start_image,
    preflight_veo_request,
    start_image_mime,
    veo_config_kwargs,
)
from docprod.providers.paid_cache import PaidArtifactCache
from docprod.providers.video_base import VideoShotRequest
from docprod.providers.video_capabilities import capabilities_for
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
        negative_prompt="dialogue, invented logos, impossible hands",
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
    config = captured["config"]
    assert isinstance(source, types.GenerateVideosSource)
    assert source.prompt
    assert "NO dialogue" in source.prompt
    assert "Audio:" in source.prompt
    assert "invented logos" in source.prompt
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
    cfg_alias = config.model_dump(mode="python", by_alias=True, exclude_none=True)
    assert "negativePrompt" not in cfg_alias
    assert config.negative_prompt is None
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
    assert "Scene:" in text
    assert req.prompt in text
    assert "Audio:" in text
    assert "warehouse" in text
    assert "NO dialogue" in text
    assert "NO narration" in text
    assert "Constraints:" in text
    assert "invented logos" in text
    assert text.lower().count("dialogue") <= 3


def test_lite_omits_negative_prompt_and_folds_constraints(tmp_path: Path) -> None:
    caps = capabilities_for("veo-3.1-lite-generate-preview")
    assert caps.negative_prompt is False
    path = tmp_path / "start.jpg"
    _write_image(path, "JPEG")
    request = _request(path)
    prompt = build_veo_prompt(request, caps)
    assert prompt
    assert "Audio:" in prompt
    kwargs = veo_config_kwargs(request, caps)
    assert "negative_prompt" not in kwargs
    from google.genai import types

    config = types.GenerateVideosConfig(**kwargs)
    dumped = config.model_dump(mode="python", by_alias=True, exclude_none=True)
    assert "negativePrompt" not in dumped
    blob = str(dumped).lower()
    assert "negativeprompt" not in blob.replace("_", "")


def test_constraint_dedupe() -> None:
    items = constraint_items("dialogue, NO dialogue, dialogue, invented logos")
    assert items.count("dialogue") == 1
    assert "invented logos" in items


def test_unsupported_duration_fails_before_network(tmp_path: Path) -> None:
    path = tmp_path / "start.jpg"
    _write_image(path, "JPEG")
    request = _request(path)
    request.duration_seconds = 4
    settings = Settings(_env_file=None, allow_paid_apis=True, gemini_api_key="unused")

    class Boom:
        def generate_videos(self, **_kwargs: object) -> None:
            raise AssertionError("network must not be called")

    provider = GoogleVeoProvider(
        settings=settings,
        client=SimpleNamespace(models=Boom(), files=SimpleNamespace()),
    )
    with pytest.raises(ValueError, match="Unsupported Veo duration"):
        provider.generate_shot(request, confirm_paid=True)


def test_maple_lite_requests_serialize_without_negative_prompt() -> None:
    caps = capabilities_for("veo-3.1-lite-generate-preview")
    root = default_projects_root() / "maple_heist_canary"
    paths = ProjectPaths(root=root)
    from google.genai import types

    for unit in ("au_0005_0006", "au_0025"):
        request = _shot_request(paths, unit)
        prompt = preflight_veo_request(request, caps)
        image = load_local_start_image(request.image_path)
        source = types.GenerateVideosSource(prompt=prompt, image=image)
        config = types.GenerateVideosConfig(**veo_config_kwargs(request, caps))
        assert caps.model_id == "veo-3.1-lite-generate-preview"
        assert isinstance(source.image, types.Image)
        assert source.image.image_bytes
        assert str(source.image.mime_type).startswith("image/")
        assert "Scene:" in source.prompt
        motion, native, _neg = SHOTS[unit]
        assert motion[:40] in source.prompt
        assert native[:20] in source.prompt
        assert "Audio:" in source.prompt
        assert "Constraints:" in source.prompt
        assert len(source.prompt) <= caps.max_prompt_chars
        dumped = config.model_dump(mode="python", by_alias=True, exclude_none=True)
        assert dumped["durationSeconds"] == 8
        assert dumped["resolution"] == "720p"
        assert dumped["aspectRatio"] == "16:9"
        assert dumped["numberOfVideos"] == 1
        assert "negativePrompt" not in dumped
        aliased_source = source.model_dump(mode="python", by_alias=True)
        assert "imageBytes" in aliased_source["image"]
        assert aliased_source["image"]["mimeType"].startswith("image/")
