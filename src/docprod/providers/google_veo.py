from __future__ import annotations

import mimetypes
import time
from pathlib import Path
from typing import Any

from docprod.config import Settings, get_settings, require_gemini_api_key, require_paid_call_allowed
from docprod.providers.video_base import VideoShotRequest, VideoShotResult

ALLOWED_START_MIME = frozenset({"image/jpeg", "image/png", "image/webp"})
_SUFFIX_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


def start_image_mime(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    mime = guessed or _SUFFIX_MIME.get(path.suffix.lower(), "")
    if mime == "image/jpg":
        mime = "image/jpeg"
    if mime not in ALLOWED_START_MIME:
        raise ValueError(
            f"Unsupported Veo start image MIME {mime or 'unknown'} for {path.name}. "
            "Use image/jpeg, image/png, or image/webp."
        )
    return mime


def load_local_start_image(path: Path) -> Any:
    """Convert a local keyframe Path to google.genai.types.Image. No Files API."""
    if not path.is_file():
        raise FileNotFoundError(f"Missing Veo start image {path}")
    mime = start_image_mime(path)
    from google.genai import types

    try:
        image = types.Image.from_file(location=str(path), mime_type=mime)
    except (TypeError, ValueError, OSError):
        image = types.Image(image_bytes=path.read_bytes(), mime_type=mime)
    if not getattr(image, "image_bytes", None):
        raise ValueError(f"Veo start image has no bytes: {path}")
    if not str(getattr(image, "mime_type", "")).startswith("image/"):
        raise ValueError(f"Veo start image missing image MIME: {path}")
    return image


def combined_veo_prompt(request: VideoShotRequest) -> str:
    prompt = request.prompt
    if request.native_audio_prompt:
        prompt = f"{prompt}\n\nNative audio: {request.native_audio_prompt}"
    return prompt


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
        image = load_local_start_image(request.image_path)
        prompt = combined_veo_prompt(request)
        from google.genai import types

        source = types.GenerateVideosSource(prompt=prompt, image=image)
        client = self._client_or_create()
        operation = client.models.generate_videos(
            model=self.model,
            source=source,
            config=types.GenerateVideosConfig(
                number_of_videos=request.count,
                duration_seconds=request.duration_seconds,
                resolution=request.resolution,
                aspect_ratio=request.aspect_ratio,
                negative_prompt=request.negative_prompt or None,
            ),
        )
        while not getattr(operation, "done", True):
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
