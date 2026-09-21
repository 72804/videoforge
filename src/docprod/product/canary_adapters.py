from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from docprod.audio.models import TTS_ONCE_INSTRUCTIONS
from docprod.product.canary_cost import (
    CANARY_IMAGE_FORMAT,
    CANARY_IMAGE_QUALITY,
    CANARY_IMAGE_SIZE,
    CANARY_VEO_RESOLUTION,
    CANARY_VEO_SECONDS,
)
from docprod.providers.google_veo import GoogleVeoProvider, preflight_veo_request
from docprod.providers.image_config import ImageGenerationConfig
from docprod.providers.openai_image import OpenAIImageProvider
from docprod.providers.openai_tts import OpenAITTSProvider
from docprod.providers.video_base import VideoShotRequest, VideoShotResult
from docprod.research.openai_web import OpenAIResponsesProvider, extract_output_text, extract_usage


@dataclass
class AdapterResult:
    data: bytes
    text: str = ""
    usage: dict[str, Any] | None = None
    remote_operation_id: str | None = None
    billed_this_run: bool = True
    extra: dict[str, Any] | None = None


class CanaryAdapters(Protocol):
    def generate_script(self, prompt: str) -> AdapterResult: ...

    def generate_image(
        self, prompt: str, *, reference_images: list[Path] | None = None
    ) -> AdapterResult: ...

    def generate_video(self, prompt: str, image_path: Path, *, scene_id: str) -> AdapterResult: ...

    def recover_video(self, prompt: str, image_path: Path, *, scene_id: str) -> AdapterResult: ...

    def preflight_video(self, prompt: str, image_path: Path, *, scene_id: str) -> None: ...

    def generate_tts(self, script: str) -> AdapterResult: ...


class LiveOpenAICanaryAdapters:
    """Thin wrappers around existing OpenAI / Veo adapters. No duplicate HTTP clients."""

    def __init__(
        self,
        *,
        text: OpenAIResponsesProvider | None = None,
        image: OpenAIImageProvider | None = None,
        tts: OpenAITTSProvider | None = None,
        veo: GoogleVeoProvider | None = None,
        script_model: str = "gpt-5.6-luna",
    ) -> None:
        size_cfg = ImageGenerationConfig(
            model="gpt-image-2.5-flare",
            size=CANARY_IMAGE_SIZE,
            quality=CANARY_IMAGE_QUALITY,
            output_format=CANARY_IMAGE_FORMAT,
        )
        self.text = text or OpenAIResponsesProvider()
        self.image = image or OpenAIImageProvider(config=size_cfg)
        self.tts = tts or OpenAITTSProvider()
        self.veo = veo or GoogleVeoProvider()
        self.script_model = script_model

    def generate_script(self, prompt: str) -> AdapterResult:
        instructions = (
            "Write a short CUSTOM_STORY video script. Return JSON only with keys "
            "duration_seconds and scenes. scenes is an array of 2-5 objects with "
            "narration, visual, motion, duration_seconds, wants_video. "
            "At most one scene may set wants_video true. Target 15-30 seconds. "
            "English. One young male protagonist. Simple visual beats."
        )
        response = self.text.create(
            model=self.script_model,
            instructions=instructions,
            input_text=prompt,
            confirm_paid=True,
            allow_retry=False,
        )
        payload = response.model_dump() if hasattr(response, "model_dump") else {}
        text = extract_output_text(response, payload if isinstance(payload, dict) else {})
        usage_model = extract_usage(
            response,
            model=self.script_model,
            web_search_calls=0,
            elapsed=0.0,
            request_count=1,
        )
        usage = {
            "input_tokens": usage_model.input_tokens,
            "output_tokens": usage_model.output_tokens,
        }
        return AdapterResult(data=text.encode("utf-8"), text=text, usage=usage)

    def generate_image(
        self, prompt: str, *, reference_images: list[Path] | None = None
    ) -> AdapterResult:
        result = self.image.generate(
            prompt,
            confirm_paid=True,
            max_attempts=1,
            reference_images=reference_images,
        )
        usage = dict(result.usage) if result.usage else None
        return AdapterResult(data=result.image_bytes, usage=usage)

    def generate_video(self, prompt: str, image_path: Path, *, scene_id: str) -> AdapterResult:
        shot = self.veo.generate_shot(
            self._request(prompt, image_path, scene_id),
            confirm_paid=True,
            use_cache=True,
        )
        return self._from_shot(shot)

    def recover_video(self, prompt: str, image_path: Path, *, scene_id: str) -> AdapterResult:
        shot = self.veo.generate_shot(
            self._request(prompt, image_path, scene_id),
            confirm_paid=False,
            use_cache=True,
        )
        return self._from_shot(shot)

    def preflight_video(self, prompt: str, image_path: Path, *, scene_id: str) -> None:
        request = self._request(prompt, image_path, scene_id)
        preflight_veo_request(request, self.veo.capabilities)

    def generate_tts(self, script: str) -> AdapterResult:
        audio, usage = self.tts.synthesize(
            script,
            confirm_paid=True,
            instructions=(
                f"{TTS_ONCE_INSTRUCTIONS} Speak English as a calm cinematic narrator. "
                "Measured pace, clear diction, restrained emotion."
            ),
            max_attempts=1,
        )
        usage_dict = dict(usage) if isinstance(usage, dict) else None
        return AdapterResult(data=audio, usage=usage_dict)

    def _request(self, prompt: str, image_path: Path, scene_id: str) -> VideoShotRequest:
        return VideoShotRequest(
            prompt=prompt,
            negative_prompt="text overlay, watermark, extra people",
            image_path=image_path,
            duration_seconds=CANARY_VEO_SECONDS,
            aspect_ratio="9:16",
            resolution=CANARY_VEO_RESOLUTION,
            count=1,
            asset_unit_id=scene_id,
            identity_key="nolan",
        )

    def _from_shot(self, shot: VideoShotResult) -> AdapterResult:
        meta = shot.metadata or {}
        billed = str(meta.get("billed_this_run") or "true").lower() == "true"
        return AdapterResult(
            data=shot.video_bytes,
            remote_operation_id=str(meta.get("operation_name") or "") or None,
            billed_this_run=billed,
            extra=dict(meta),
        )


class FakeCanaryAdapters:
    """In-process fakes. Never opens sockets."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.script_scenes = 3
        self.video_submits = 0
        self.remote_id = "fake-veo-op-1"
        self.preflight_error: str | None = None
        self.last_tts_text = ""

    def generate_script(self, prompt: str) -> AdapterResult:
        self.calls.append("script")
        scenes = []
        for index in range(self.script_scenes):
            scenes.append(
                {
                    "narration": f"Beat {index + 1} of the suitcase story.",
                    "visual": f"{prompt} beat {index + 1}",
                    "motion": "subtle camera drift",
                    "duration_seconds": 8,
                    "wants_video": index == 1,
                }
            )
        body = json.dumps({"duration_seconds": 24, "scenes": scenes})
        return AdapterResult(
            data=body.encode("utf-8"),
            text=body,
            usage={"input_tokens": 800, "output_tokens": 400},
        )

    def generate_image(
        self, prompt: str, *, reference_images: list[Path] | None = None
    ) -> AdapterResult:
        self.calls.append("image")
        _ = prompt, reference_images
        return AdapterResult(
            data=b"\xff\xd8fakejpeg",
            usage={"input_tokens": 400, "output_tokens": 1584},
        )

    def generate_video(self, prompt: str, image_path: Path, *, scene_id: str) -> AdapterResult:
        self.calls.append("video")
        self.video_submits += 1
        _ = prompt, image_path, scene_id
        return AdapterResult(
            data=b"fake-mp4",
            remote_operation_id=self.remote_id,
            billed_this_run=True,
        )

    def recover_video(self, prompt: str, image_path: Path, *, scene_id: str) -> AdapterResult:
        self.calls.append("video-recover")
        _ = prompt, image_path, scene_id
        return AdapterResult(
            data=b"fake-mp4",
            remote_operation_id=self.remote_id,
            billed_this_run=False,
        )

    def preflight_video(self, prompt: str, image_path: Path, *, scene_id: str) -> None:
        _ = prompt, image_path, scene_id
        if self.preflight_error:
            raise ValueError(self.preflight_error)

    def generate_tts(self, script: str) -> AdapterResult:
        self.calls.append("tts")
        self.last_tts_text = script
        return AdapterResult(
            data=b"RIFF....WAVEfmt",
            usage={"input_tokens": 120, "output_tokens": 2000},
        )
