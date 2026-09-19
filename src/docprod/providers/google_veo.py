from __future__ import annotations

import mimetypes
import re
import time
from pathlib import Path
from typing import Any

from docprod.config import Settings, get_settings, require_gemini_api_key, require_paid_call_allowed
from docprod.providers.paid_cache import PaidArtifactCache, veo_request_hash
from docprod.providers.pricing import veo_cost_usd
from docprod.providers.video_base import VideoShotRequest, VideoShotResult
from docprod.providers.video_capabilities import VideoModelCapabilities, capabilities_for
from docprod.storage.hashing import file_sha256
from docprod.storage.identity import poll_delays

ALLOWED_START_MIME = frozenset({"image/jpeg", "image/png", "image/webp"})
_SUFFIX_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}
_SPLIT = re.compile(r"[,;\n]+")
_PREFIX = re.compile(r"^(?:no|not|avoid|without)\s+", re.IGNORECASE)


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


def constraint_items(text: str) -> list[str]:
    items: list[str] = []
    seen: set[str] = set()
    for raw in _SPLIT.split(text or ""):
        cleaned = _PREFIX.sub("", raw).strip(" -.\t")
        key = re.sub(r"\s+", " ", cleaned).lower()
        if len(key) < 3 or key in seen:
            continue
        seen.add(key)
        items.append(key)
    return items


def build_veo_prompt(
    request: VideoShotRequest,
    capabilities: VideoModelCapabilities | None = None,
) -> str:
    caps = capabilities or capabilities_for("veo-3.1-lite-generate-preview")
    scene = request.prompt.strip()
    audio = request.native_audio_prompt.strip()
    if not scene:
        raise ValueError("Veo motion prompt is empty")
    parts = [f"Scene:\n{scene}"]
    if audio:
        parts.append(f"Audio:\n{audio}")
    existing = f"{scene}\n{audio}".lower()
    folded: list[str] = []
    if not caps.negative_prompt:
        for item in constraint_items(request.negative_prompt):
            if item in existing or f"no {item}" in existing:
                continue
            folded.append(item)
        if folded:
            lines = "\n".join(f"- no {item}" for item in folded)
            parts.append(f"Constraints:\n{lines}")
    prompt = "\n\n".join(parts)
    if len(prompt) > caps.max_prompt_chars:
        raise ValueError(
            f"Compiled Veo prompt is {len(prompt)} chars; max is {caps.max_prompt_chars}"
        )
    return prompt


def combined_veo_prompt(request: VideoShotRequest) -> str:
    return build_veo_prompt(request)


def preflight_veo_request(
    request: VideoShotRequest,
    capabilities: VideoModelCapabilities,
) -> str:
    if not capabilities.image_to_video:
        raise ValueError(f"{capabilities.model_id} does not support image-to-video")
    if request.duration_seconds not in capabilities.duration_options:
        raise ValueError(
            f"Unsupported Veo duration {request.duration_seconds}s for {capabilities.model_id}"
        )
    if request.resolution not in capabilities.resolution_options:
        raise ValueError(
            f"Unsupported Veo resolution {request.resolution!r} for {capabilities.model_id}"
        )
    if request.aspect_ratio not in capabilities.aspect_ratios:
        raise ValueError(
            f"Unsupported Veo aspect ratio {request.aspect_ratio!r} for {capabilities.model_id}"
        )
    if request.count < 1 or request.count > capabilities.max_outputs:
        raise ValueError(
            f"Unsupported Veo output count {request.count} for {capabilities.model_id}"
        )
    load_local_start_image(request.image_path)
    return build_veo_prompt(request, capabilities)


def veo_config_kwargs(
    request: VideoShotRequest,
    capabilities: VideoModelCapabilities,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "number_of_videos": request.count,
        "duration_seconds": request.duration_seconds,
        "resolution": request.resolution,
        "aspect_ratio": request.aspect_ratio,
    }
    if capabilities.negative_prompt and request.negative_prompt.strip():
        payload["negative_prompt"] = request.negative_prompt.strip()
    return payload


def native_negative_for_hash(
    request: VideoShotRequest, capabilities: VideoModelCapabilities
) -> str:
    if capabilities.negative_prompt:
        return request.negative_prompt
    return ""


class GoogleVeoProvider:
    name = "google"

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        client: Any = None,
        cache: PaidArtifactCache | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self.model = self._settings.video_model
        self._client = client
        self._cache = cache if cache is not None else PaidArtifactCache()
        self.capabilities = capabilities_for(self.model)

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

    def generate_shot(
        self,
        request: VideoShotRequest,
        *,
        confirm_paid: bool,
        use_cache: bool = True,
    ) -> VideoShotResult:
        prompt = preflight_veo_request(request, self.capabilities)
        digest = veo_request_hash(
            model=self.model,
            image_sha256=file_sha256(request.image_path),
            prompt=prompt,
            negative_prompt=native_negative_for_hash(request, self.capabilities),
            duration_seconds=request.duration_seconds,
            aspect_ratio=request.aspect_ratio,
            resolution=request.resolution,
            count=request.count,
        )
        if use_cache:
            cached = self._cache.get("veo", digest)
            if cached is not None:
                path, _meta = cached
                return VideoShotResult(
                    video_bytes=path.read_bytes(),
                    provider=self.name,
                    model=self.model,
                    duration_seconds=float(request.duration_seconds),
                    prompt=prompt,
                    has_native_audio=True,
                    metadata={
                        "start_image": request.image_path.name,
                        "cache_hit": "true",
                        "request_hash": digest,
                    },
                )
        require_paid_call_allowed(self.name, confirm_paid=confirm_paid, settings=self._settings)
        from google.genai import types

        image = load_local_start_image(request.image_path)
        source = types.GenerateVideosSource(prompt=prompt, image=image)
        config = types.GenerateVideosConfig(**veo_config_kwargs(request, self.capabilities))
        client = self._client_or_create()
        operation = client.models.generate_videos(
            model=self.model,
            source=source,
            config=config,
        )
        for delay in poll_delays():
            if getattr(operation, "done", True):
                break
            time.sleep(delay)
            operation = client.operations.get(operation)
        if not getattr(operation, "done", True):
            raise RuntimeError("Veo operation timed out")
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
        self._cache.put(
            "veo",
            digest,
            payload,
            suffix=".mp4",
            meta={
                "provider": self.name,
                "model": self.model,
                "prompt_hash": digest,
                "start_image": request.image_path.name,
                "status": "ok",
                "cost_usd": veo_cost_usd(request.duration_seconds),
            },
        )
        return VideoShotResult(
            video_bytes=payload,
            provider=self.name,
            model=self.model,
            duration_seconds=float(request.duration_seconds),
            prompt=prompt,
            has_native_audio=True,
            metadata={"start_image": request.image_path.name, "request_hash": digest},
        )
