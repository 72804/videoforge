from __future__ import annotations

from pathlib import Path
from typing import Any

from docprod.config import Settings, get_settings, require_gemini_api_key, require_paid_call_allowed
from docprod.providers.video_base import VideoShotRequest, VideoShotResult


class GoogleVeoProvider:
    name = "google"

    def __init__(self, *, settings: Settings | None = None, client: Any = None) -> None:
        self._settings = settings or get_settings()
        self.model = self._settings.video_model
        self._client = client

    def _client_or_create(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from google import genai
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("google-genai is required for Veo generation") from exc
        key = require_gemini_api_key(self._settings)
        self._client = genai.Client(api_key=key)
        return self._client

    def generate_shot(self, request: VideoShotRequest, *, confirm_paid: bool) -> VideoShotResult:
        require_paid_call_allowed(self.name, confirm_paid=confirm_paid, settings=self._settings)
        if not request.image_path.is_file():
            raise FileNotFoundError(f"Missing Veo start image {request.image_path}")
        client = self._client_or_create()
        from google.genai import types

        uploaded = client.files.upload(file=request.image_path)
        prompt = request.prompt
        if request.native_audio_prompt:
            prompt = f"{prompt}\n\nNative audio: {request.native_audio_prompt}"
        operation = client.models.generate_videos(
            model=self.model,
            prompt=prompt,
            image=uploaded,
            config=types.GenerateVideosConfig(
                aspect_ratio=request.aspect_ratio,
                resolution=request.resolution,
                duration_seconds=request.duration_seconds,
                number_of_videos=request.count,
                negative_prompt=request.negative_prompt or None,
            ),
        )
        while not getattr(operation, "done", True):
            import time

            time.sleep(8)
            operation = client.operations.get(operation)
        response = getattr(operation, "response", None) or getattr(operation, "result", None)
        videos = getattr(response, "generated_videos", None) if response is not None else None
        if not videos:
            raise RuntimeError("Veo returned no video")
        generated = videos[0]
        video_file = generated.video
        dest = Path(str(request.image_path) + ".veo.tmp.mp4")
        client.files.download(file=video_file, download_path=str(dest))
        payload = dest.read_bytes()
        dest.unlink(missing_ok=True)
        return VideoShotResult(
            video_bytes=payload,
            provider=self.name,
            model=self.model,
            duration_seconds=float(request.duration_seconds),
            prompt=prompt,
            has_native_audio=True,
            metadata={"start_image": request.image_path.name},
        )
