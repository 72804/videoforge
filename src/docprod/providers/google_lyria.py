from __future__ import annotations

from typing import Any

from docprod.config import Settings, get_settings, require_gemini_api_key, require_paid_call_allowed
from docprod.providers.music_base import MusicGenerateRequest, MusicGenerateResult
from docprod.providers.pricing import LYRIA_IMAGE_LIMIT


class GoogleLyriaProvider:
    name = "google"

    def __init__(self, *, settings: Settings | None = None, client: Any = None) -> None:
        self._settings = settings or get_settings()
        self.model = self._settings.music_model
        self._client = client

    def _client_or_create(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from google import genai
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("google-genai is required for Lyria generation") from exc
        key = require_gemini_api_key(self._settings)
        self._client = genai.Client(api_key=key)
        return self._client

    def generate_music(
        self, request: MusicGenerateRequest, *, confirm_paid: bool
    ) -> MusicGenerateResult:
        require_paid_call_allowed(self.name, confirm_paid=confirm_paid, settings=self._settings)
        client = self._client_or_create()
        from google.genai import types

        contents: list[Any] = [request.prompt]
        for path in request.image_paths[:LYRIA_IMAGE_LIMIT]:
            if path.is_file():
                contents.append(
                    types.Part.from_bytes(data=path.read_bytes(), mime_type="image/jpeg")
                )
        config = types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            response_format={"audio": {"mime_type": "audio/wav"}} if request.wav else None,
        )
        response = client.models.generate_content(
            model=self.model, contents=contents, config=config
        )
        audio = b""
        mime = "audio/wav" if request.wav else "audio/mpeg"
        for part in getattr(response, "parts", None) or []:
            inline = getattr(part, "inline_data", None)
            if inline is not None and getattr(inline, "data", None):
                audio = inline.data
                mime = getattr(inline, "mime_type", None) or mime
                break
        if not audio:
            raise RuntimeError("Lyria returned no audio")
        return MusicGenerateResult(
            audio_bytes=audio,
            provider=self.name,
            model=self.model,
            mime=mime,
            prompt=request.prompt,
            synthid=None,
            metadata={"image_count": str(min(len(request.image_paths), LYRIA_IMAGE_LIMIT))},
        )


class DisabledAdaptiveMusicProvider:
    name = "google"
    model = "lyria-realtime-exp"
    enabled = False

    def is_available(self) -> bool:
        return False
