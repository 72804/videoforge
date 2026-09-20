from __future__ import annotations

import base64
import time
from pathlib import Path
from typing import Any

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    OpenAI,
    RateLimitError,
)

from docprod.config import Settings, get_settings, require_openai_api_key, require_paid_call_allowed
from docprod.providers.image_config import ImageGenerationConfig
from docprod.storage.hashing import content_hash


def image_request_hash(
    *,
    prompt: str,
    config: ImageGenerationConfig,
    seed: int | None,
    extra: dict[str, str] | None = None,
) -> str:
    payload = {
        "provider": config.provider,
        "model": config.model,
        "prompt": prompt,
        "size": config.size,
        "quality": config.quality,
        "output_format": config.output_format,
        "seed": seed,
    }
    if extra:
        payload.update(extra)
    return content_hash(payload)


def _usage_dict(usage: object | None) -> dict[str, int | float | str] | None:
    if usage is None:
        return None
    if isinstance(usage, dict):
        return {str(k): v for k, v in usage.items() if isinstance(v, (int, float, str))}
    dump = getattr(usage, "model_dump", None)
    if callable(dump):
        payload = dump()
        if isinstance(payload, dict):
            flat: dict[str, int | float | str] = {}
            for key, value in payload.items():
                if isinstance(value, (int, float, str)):
                    flat[str(key)] = value
            return flat or None
    return None


def _is_transient(exc: BaseException) -> bool:
    if isinstance(exc, APIConnectionError | APITimeoutError | RateLimitError):
        return True
    if isinstance(exc, APIStatusError) and exc.status_code in {429, 500, 502, 503, 504}:
        return True
    return False


class OpenAIImageResult:
    def __init__(
        self,
        *,
        image_bytes: bytes,
        revised_prompt: str | None,
        usage: dict[str, int | float | str] | None,
        elapsed_seconds: float,
        raw_model: str,
    ) -> None:
        self.image_bytes = image_bytes
        self.revised_prompt = revised_prompt
        self.usage = usage
        self.elapsed_seconds = elapsed_seconds
        self.raw_model = raw_model


class OpenAIImageProvider:
    """Paid OpenAI Images API adapter. Tests inject a fake client."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        config: ImageGenerationConfig | None = None,
        client: Any | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.config = config or ImageGenerationConfig.from_settings(self.settings)
        self._client = client

    def _client_or_create(self) -> Any:
        if self._client is not None:
            return self._client
        key = require_openai_api_key(self.settings)
        return OpenAI(api_key=key)

    def generate(
        self,
        prompt: str,
        *,
        confirm_paid: bool,
        seed: int | None = None,
        max_attempts: int = 2,
        reference_images: list[Path] | None = None,
    ) -> OpenAIImageResult:
        require_paid_call_allowed("openai", confirm_paid=confirm_paid, settings=self.settings)
        require_openai_api_key(self.settings)
        refs = [Path(path) for path in (reference_images or []) if Path(path).is_file()]
        kwargs: dict[str, Any] = {
            "model": self.config.model,
            "prompt": prompt,
            "size": self.config.size,
            "quality": self.config.quality,
            "output_format": self.config.output_format,
            "n": 1,
        }
        client = self._client_or_create()
        started = time.perf_counter()
        response = None
        last_error: BaseException | None = None
        handles: list[Any] = []
        try:
            if refs:
                handles = [path.open("rb") for path in refs]
                kwargs["image"] = handles if len(handles) > 1 else handles[0]
            for attempt in range(max(1, max_attempts)):
                try:
                    if refs:
                        response = client.images.edit(**kwargs)
                    else:
                        response = client.images.generate(**kwargs)
                    last_error = None
                    break
                except Exception as exc:
                    last_error = exc
                    if attempt == 0 and _is_transient(exc) and max_attempts > 1:
                        continue
                    raise
        finally:
            for handle in handles:
                handle.close()
        if response is None:
            raise last_error or RuntimeError("OpenAI image generation returned no response")
        elapsed = time.perf_counter() - started
        data = getattr(response, "data", None) or []
        if not data:
            raise RuntimeError("OpenAI image response contained no image data")
        first = data[0]
        encoded = getattr(first, "b64_json", None)
        if not encoded:
            raise RuntimeError("OpenAI image response missing b64_json")
        image_bytes = base64.b64decode(encoded)
        if not image_bytes:
            raise RuntimeError("OpenAI image payload decoded to empty bytes")
        return OpenAIImageResult(
            image_bytes=image_bytes,
            revised_prompt=getattr(first, "revised_prompt", None),
            usage=_usage_dict(getattr(response, "usage", None)),
            elapsed_seconds=elapsed,
            raw_model=getattr(response, "model", None) or self.config.model,
        )
