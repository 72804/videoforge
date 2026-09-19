from __future__ import annotations

import time
from typing import Any

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    OpenAI,
    RateLimitError,
)

from docprod.audio.models import DEFAULT_VOICE_INSTRUCTIONS
from docprod.config import Settings, get_settings, require_openai_api_key, require_paid_call_allowed
from docprod.storage.hashing import content_hash


def tts_request_hash(
    *,
    model: str,
    voice: str,
    speed: float,
    instructions: str,
    script: str,
) -> str:
    return content_hash(
        {
            "provider": "openai",
            "model": model,
            "voice": voice,
            "speed": speed,
            "instructions": instructions,
            "script": script,
            "response_format": "wav",
        }
    )


def _is_transient(exc: BaseException) -> bool:
    if isinstance(exc, APIConnectionError | APITimeoutError | RateLimitError):
        return True
    if isinstance(exc, APIStatusError) and exc.status_code in {429, 500, 502, 503, 504}:
        return True
    return False


def _audio_bytes(response: Any) -> bytes:
    content = getattr(response, "content", None)
    if isinstance(content, bytes):
        return content
    read = getattr(response, "read", None)
    if callable(read):
        payload = read()
        if isinstance(payload, bytes):
            return payload
    raise RuntimeError("OpenAI TTS response had no audio bytes")


class OpenAITTSProvider:
    def __init__(self, *, settings: Settings | None = None, client: Any | None = None) -> None:
        self.settings = settings or get_settings()
        self._client = client
        self.request_count = 0

    def _client_or_create(self) -> Any:
        if self._client is not None:
            return self._client
        return OpenAI(api_key=require_openai_api_key(self.settings))

    def synthesize(
        self,
        script: str,
        *,
        confirm_paid: bool,
        instructions: str = DEFAULT_VOICE_INSTRUCTIONS,
        max_attempts: int = 1,
    ) -> tuple[bytes, dict[str, Any] | None]:
        require_paid_call_allowed("openai", confirm_paid=confirm_paid, settings=self.settings)
        require_openai_api_key(self.settings)
        client = self._client_or_create()
        kwargs = {
            "model": self.settings.openai_tts_model,
            "voice": self.settings.openai_tts_voice,
            "input": script,
            "instructions": instructions,
            "response_format": "wav",
            "speed": self.settings.openai_tts_speed,
        }
        last_error: BaseException | None = None
        attempts = max(1, max_attempts)
        for attempt in range(attempts):
            try:
                self.request_count += 1
                response = client.audio.speech.create(**kwargs)
                usage = None
                raw_usage = getattr(response, "usage", None)
                if isinstance(raw_usage, dict):
                    usage = raw_usage
                elif raw_usage is not None and hasattr(raw_usage, "model_dump"):
                    dumped = raw_usage.model_dump()
                    if isinstance(dumped, dict):
                        usage = {
                            str(k): v
                            for k, v in dumped.items()
                            if isinstance(v, (int, float, str))
                        }
                return _audio_bytes(response), usage
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt + 1 < attempts and _is_transient(exc):
                    time.sleep(0.4)
                    continue
                raise
        raise RuntimeError(f"TTS failed: {last_error}")
