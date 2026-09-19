from __future__ import annotations

import mimetypes
from typing import Any

from docprod.config import Settings, get_settings, require_gemini_api_key, require_paid_call_allowed
from docprod.providers.music_base import MusicGenerateRequest, MusicGenerateResult
from docprod.providers.paid_cache import PaidArtifactCache, lyria_request_hash
from docprod.providers.pricing import LYRIA_IMAGE_LIMIT
from docprod.storage.hashing import file_sha256

ALLOWED_IMAGE_MIME = frozenset({"image/jpeg", "image/png", "image/webp"})


def preflight_lyria_request(request: MusicGenerateRequest) -> None:
    text = request.prompt.upper()
    if not request.prompt.strip():
        raise ValueError("Lyria prompt is empty")
    if "INSTRUMENTAL" not in text:
        raise ValueError("Lyria prompt must require INSTRUMENTAL ONLY")
    if "NO VOCALS" not in text and "NO LYRICS" not in text:
        raise ValueError("Lyria prompt must forbid vocals/lyrics")
    if len(request.image_paths) > LYRIA_IMAGE_LIMIT:
        raise ValueError(f"Lyria image cap is {LYRIA_IMAGE_LIMIT}")
    for path in request.image_paths:
        if not path.is_file():
            raise FileNotFoundError(f"Lyria image missing: {path}")
        mime, _ = mimetypes.guess_type(path.name)
        if path.suffix.lower() in {".jpg", ".jpeg"}:
            mime = mime or "image/jpeg"
        if mime not in ALLOWED_IMAGE_MIME:
            raise ValueError(f"Unsupported Lyria image MIME {mime} for {path.name}")


class GoogleLyriaProvider:
    name = "google"

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        client: Any = None,
        cache: PaidArtifactCache | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self.model = self._settings.music_model
        self._client = client
        self._cache = cache if cache is not None else PaidArtifactCache()

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
        self,
        request: MusicGenerateRequest,
        *,
        confirm_paid: bool,
        use_cache: bool = True,
    ) -> MusicGenerateResult:
        preflight_lyria_request(request)
        image_hashes = [file_sha256(path) for path in request.image_paths if path.is_file()]
        digest = lyria_request_hash(
            model=self.model,
            prompt=request.prompt,
            image_sha256s=image_hashes,
            duration_hint_seconds=request.duration_hint_seconds,
            wav=request.wav,
        )
        if use_cache:
            cached = self._cache.get("lyria", digest)
            if cached is not None:
                path, _meta = cached
                return MusicGenerateResult(
                    audio_bytes=path.read_bytes(),
                    provider=self.name,
                    model=self.model,
                    mime="audio/wav" if request.wav else "audio/mpeg",
                    prompt=request.prompt,
                    metadata={"cache_hit": "true", "request_hash": digest},
                )
        require_paid_call_allowed(self.name, confirm_paid=confirm_paid, settings=self._settings)
        client = self._client_or_create()
        from google.genai import types

        contents: list[Any] = [request.prompt]
        for path in request.image_paths[:LYRIA_IMAGE_LIMIT]:
            mime, _ = mimetypes.guess_type(path.name)
            if path.suffix.lower() in {".jpg", ".jpeg"}:
                mime = "image/jpeg"
            contents.append(
                types.Part.from_bytes(data=path.read_bytes(), mime_type=mime or "image/jpeg")
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
        self._cache.put(
            "lyria",
            digest,
            audio,
            suffix=".wav" if request.wav else ".mp3",
            meta={"provider": self.name, "model": self.model, "status": "ok"},
        )
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
