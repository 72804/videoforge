from __future__ import annotations

import base64
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from docprod.config import Settings
from docprod.exceptions import MissingApiKeyError, PaidApiDisabledError, PaidApiNotConfirmedError
from docprod.models.enums import AssetStrategy, Mood, TransitionType, VisualEffect
from docprod.models.scene import GenerationSpec, Scene, ScenePlan
from docprod.pipeline.generate_image_stage import execute_generate_image
from docprod.providers.image_config import GeneratedImageManifest, ImageGenerationConfig
from docprod.providers.openai_image import OpenAIImageProvider
from docprod.storage.hashing import file_sha256
from docprod.storage.json_store import load_model
from docprod.storage.paths import ProjectPaths

JPEG_BYTES = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xdb\x00C\x00" + bytes([8] * 64) + b"\xff\xd9"
)


def _settings(**kwargs: object) -> Settings:
    payload: dict[str, object] = {
        "allow_paid_apis": True,
        "openai_api_key": SecretStr("test-not-a-real-key"),
        "log_level": "INFO",
    }
    payload.update(kwargs)
    return Settings(**payload)


def _scene() -> Scene:
    return Scene(
        id="scene_0003",
        start=0.0,
        end=4.0,
        duration=4.0,
        narration="Three dogs wait beside an abandoned ATM.",
        visual_intent="Wide shot of three dogs at a night-time cash machine.",
        asset_strategy=AssetStrategy.ai_image,
        effect=VisualEffect.slow_push_in,
        transition=TransitionType.cut,
        mood=Mood.mysterious,
        subtitle="Three dogs wait",
        generation=GenerationSpec(image_prompt="three dogs beside an ATM at night"),
        metadata={"primary_category": "crime"},
    )


def _plan() -> ScenePlan:
    scene = _scene()
    return ScenePlan(project_id="planner_demo", scenes=[scene], total_duration=scene.end)


class FakeImages:
    def __init__(
        self,
        payload: bytes = JPEG_BYTES,
        *,
        error: Exception | None = None,
        usage: dict[str, int | float | str] | None = None,
    ) -> None:
        self.calls: list[dict[str, object]] = []
        self.payload = payload
        self.error = error
        self.usage_payload = usage if usage is not None else {"total_tokens": 12}

    def generate(self, **kwargs: object) -> SimpleNamespace:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return SimpleNamespace(
            data=[
                SimpleNamespace(
                    b64_json=base64.b64encode(self.payload).decode("ascii"),
                    revised_prompt="revised documentary still",
                )
            ],
            usage=SimpleNamespace(model_dump=lambda: dict(self.usage_payload)),
            model="gpt-image-2.5-flare",
        )

    def edit(self, **kwargs: object) -> SimpleNamespace:
        return self.generate(**kwargs)


class FakeClient:
    def __init__(self, images: FakeImages | None = None) -> None:
        self.images = images or FakeImages()


def test_provider_refuses_when_paid_disabled() -> None:
    provider = OpenAIImageProvider(
        settings=_settings(allow_paid_apis=False),
        client=FakeClient(),
    )
    with pytest.raises(PaidApiDisabledError):
        provider.generate("a still", confirm_paid=True)


def test_provider_refuses_without_confirm_paid() -> None:
    provider = OpenAIImageProvider(settings=_settings(), client=FakeClient())
    with pytest.raises(PaidApiNotConfirmedError, match="confirm-paid"):
        provider.generate("a still", confirm_paid=False)


def test_missing_key_rejected() -> None:
    provider = OpenAIImageProvider(
        settings=_settings(openai_api_key=None),
        client=FakeClient(),
    )
    with pytest.raises(MissingApiKeyError):
        provider.generate("a still", confirm_paid=True)


def test_request_payload_uses_configured_model_size_quality() -> None:
    images = FakeImages()
    cfg = ImageGenerationConfig(
        model="gpt-image-2.5-flare",
        size="1536x864",
        quality="medium",
        output_format="jpeg",
    )
    provider = OpenAIImageProvider(settings=_settings(), config=cfg, client=FakeClient(images))
    result = provider.generate("documentary still of three dogs", confirm_paid=True)
    assert images.calls[0]["model"] == "gpt-image-2.5-flare"
    assert images.calls[0]["size"] == "1536x864"
    assert images.calls[0]["quality"] == "medium"
    assert images.calls[0]["output_format"] == "jpeg"
    assert result.image_bytes == JPEG_BYTES
    assert result.revised_prompt == "revised documentary still"
    assert result.usage == {"total_tokens": 12}


def test_generate_with_reference_uses_edit(tmp_path: Path) -> None:
    images = FakeImages()
    cfg = ImageGenerationConfig(
        model="gpt-image-2.5-flare",
        size="1536x864",
        quality="medium",
        output_format="jpeg",
    )
    ref = tmp_path / "ref.jpg"
    ref.write_bytes(JPEG_BYTES)
    provider = OpenAIImageProvider(settings=_settings(), config=cfg, client=FakeClient(images))
    provider.generate("new scene", confirm_paid=True, reference_images=[ref])
    assert "image" in images.calls[0]
    assert images.calls[0]["model"] == "gpt-image-2.5-flare"


def test_execute_writes_image_metadata_sha_and_cache(
    tmp_path: Path,
) -> None:
    paths = ProjectPaths(root=tmp_path / "planner_demo")
    images = FakeImages()
    provider = OpenAIImageProvider(settings=_settings(), client=FakeClient(images))
    first = execute_generate_image(
        paths,
        plan=_plan(),
        scene_id="scene_0003",
        confirm_paid=True,
        settings=_settings(),
        provider=provider,
    )
    image_path = paths.scene_image_path("scene_0003")
    meta_path = paths.scene_image_meta("scene_0003")
    assert image_path.is_file()
    assert image_path.read_bytes() == JPEG_BYTES
    assert first.output_sha256 == file_sha256(image_path)
    loaded = load_model(meta_path, GeneratedImageManifest)
    assert loaded.generation_status == "success"
    assert loaded.scene_id == "scene_0003"
    dumped = meta_path.read_text(encoding="utf-8").lower()
    assert "test-not-a-real-key" not in dumped
    assert "api_key" not in dumped
    assert "authorization" not in dumped
    second = execute_generate_image(
        paths,
        plan=_plan(),
        scene_id="scene_0003",
        confirm_paid=False,
        settings=_settings(),
        provider=provider,
    )
    assert second.cache_hit is True
    assert len(images.calls) == 1
    execute_generate_image(
        paths,
        plan=_plan(),
        scene_id="scene_0003",
        confirm_paid=True,
        force=True,
        settings=_settings(),
        provider=provider,
    )
    assert len(images.calls) == 2


def test_force_without_confirm_does_not_call_provider(tmp_path: Path) -> None:
    paths = ProjectPaths(root=tmp_path / "planner_demo")
    images = FakeImages()
    provider = OpenAIImageProvider(settings=_settings(), client=FakeClient(images))
    execute_generate_image(
        paths,
        plan=_plan(),
        scene_id="scene_0003",
        confirm_paid=True,
        settings=_settings(),
        provider=provider,
    )
    with pytest.raises(PaidApiNotConfirmedError):
        execute_generate_image(
            paths,
            plan=_plan(),
            scene_id="scene_0003",
            confirm_paid=False,
            force=True,
            settings=_settings(),
            provider=provider,
        )
    assert len(images.calls) == 1


def test_api_failure_preserves_previous_image(tmp_path: Path) -> None:
    paths = ProjectPaths(root=tmp_path / "planner_demo")
    images = FakeImages()
    provider = OpenAIImageProvider(settings=_settings(), client=FakeClient(images))
    execute_generate_image(
        paths,
        plan=_plan(),
        scene_id="scene_0003",
        confirm_paid=True,
        settings=_settings(),
        provider=provider,
    )
    image_path = paths.scene_image_path("scene_0003")
    original = image_path.read_bytes()
    images.error = RuntimeError("moderation blocked")
    with pytest.raises(RuntimeError, match="moderation"):
        execute_generate_image(
            paths,
            plan=_plan(),
            scene_id="scene_0003",
            confirm_paid=True,
            force=True,
            settings=_settings(),
            provider=provider,
        )
    assert image_path.read_bytes() == original
    manifest = load_model(paths.scene_image_meta("scene_0003"), GeneratedImageManifest)
    assert manifest.generation_status == "success"
    assert "failed" not in manifest.generation_status


def test_three_reference_files_submitted_together(tmp_path: Path) -> None:
    images = FakeImages()
    cfg = ImageGenerationConfig.from_settings(_settings())
    refs = []
    for name in ("a.jpg", "b.jpg", "c.jpg"):
        path = tmp_path / name
        path.write_bytes(JPEG_BYTES)
        refs.append(path)
    provider = OpenAIImageProvider(settings=_settings(), config=cfg, client=FakeClient(images))
    provider.generate("three identities", confirm_paid=True, reference_images=refs)
    payload = images.calls[0]["image"]
    assert isinstance(payload, list)
    assert len(payload) == 3


def test_refuses_more_references_than_adapter_max(tmp_path: Path) -> None:
    from docprod.providers.openai_image import OPENAI_IMAGE_EDIT_MAX_REFERENCE_FILES

    images = FakeImages()
    cfg = ImageGenerationConfig.from_settings(_settings())
    refs = []
    for index in range(OPENAI_IMAGE_EDIT_MAX_REFERENCE_FILES + 1):
        path = tmp_path / f"r{index}.jpg"
        path.write_bytes(JPEG_BYTES)
        refs.append(path)
    provider = OpenAIImageProvider(settings=_settings(), config=cfg, client=FakeClient(images))
    with pytest.raises(ValueError, match="Refusing to drop identities"):
        provider.generate("too many", confirm_paid=True, reference_images=refs)
    assert images.calls == []
