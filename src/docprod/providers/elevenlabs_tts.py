from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from docprod.config import Settings, get_settings, require_paid_call_allowed
from docprod.exceptions import MissingApiKeyError
from docprod.providers.paid_cache import PaidArtifactCache, tts_cache_hash
from docprod.providers.pricing import ELEVEN_V3_USD_PER_1K_CHARS, PRICING_AS_OF
from docprod.quality.enums import CostConfidence, PriceMode
from docprod.quality.specs import PricingSpec

ELEVEN_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
ELEVEN_MODEL_ID = "eleven_v3"
OUTPUT_FORMAT = "wav_48000"
PRICING = PricingSpec(
    mode=PriceMode.PER_CHARACTER,
    value=ELEVEN_V3_USD_PER_1K_CHARS / 1000.0,
    unit="character",
    notes="$0.10 per 1K characters (Multilingual v2/v3 API)",
    confidence=CostConfidence.KNOWN,
    pricing_as_of=PRICING_AS_OF,
    source_note="https://elevenlabs.io/pricing/api",
)


def elevenlabs_tts_hash(
    *,
    model: str,
    voice: str,
    text: str,
    instructions: str,
    language: str,
    settings: dict | None = None,
) -> str:
    return tts_cache_hash(
        model=model,
        voice=voice,
        text=text,
        instructions=instructions,
        language=language,
        settings=settings,
    )


def build_tts_payload(
    *,
    text: str,
    voice_id: str,
    language: str = "tr",
    instructions: str = "",
    stability: float | None = None,
    style: float | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "text": text,
        "model_id": ELEVEN_MODEL_ID,
        "language_code": language,
    }
    if instructions.strip():
        # v3 supports inline audio tags in text; extra instructions stay in cache hash only.
        body["previous_text"] = None
    voice_settings: dict[str, float] = {}
    if stability is not None:
        voice_settings["stability"] = stability
    if style is not None:
        voice_settings["style"] = style
    if voice_settings:
        body["voice_settings"] = voice_settings
    return {
        "url": ELEVEN_TTS_URL.format(voice_id=voice_id),
        "query": {"output_format": OUTPUT_FORMAT},
        "json": body,
        "voice_id": voice_id,
        "estimated_usd": round(len(text) * (ELEVEN_V3_USD_PER_1K_CHARS / 1000.0), 6),
    }


class ElevenLabsTTSProvider:
    """POST /v1/text-to-speech/{voice_id} with model_id eleven_v3. No calls unless confirmed."""

    def __init__(self, *, settings: Settings | None = None, transport: Any | None = None) -> None:
        self.settings = settings or get_settings()
        self.transport = transport

    def synthesize(
        self,
        text: str,
        *,
        confirm_paid: bool,
        voice_id: str = "",
        language: str = "tr",
        instructions: str = "",
        dry_run: bool = True,
        use_cache: bool = True,
    ) -> dict[str, Any]:
        voice = voice_id or self.settings.elevenlabs_voice_id.strip()
        if not voice:
            raise MissingApiKeyError(
                "ELEVENLABS_VOICE_ID is required for Eleven v3 TTS (no default celebrity voice)."
            )
        payload = build_tts_payload(
            text=text, voice_id=voice, language=language, instructions=instructions
        )
        digest = elevenlabs_tts_hash(
            model=ELEVEN_MODEL_ID,
            voice=voice,
            text=text,
            instructions=instructions,
            language=language,
            settings={"output_format": OUTPUT_FORMAT},
        )
        if use_cache:
            hit = PaidArtifactCache().get("tts", digest)
            if hit is not None:
                path, meta = hit
                return {"cached": True, "path": str(path), "meta": meta, "digest": digest}
        if dry_run:
            return {"dry_run": True, "digest": digest, "payload": payload, "paid_calls": 0}
        require_paid_call_allowed("elevenlabs", confirm_paid=confirm_paid, settings=self.settings)
        key = _require_eleven_key(self.settings)
        if self.transport is not None:
            audio = self.transport(payload, key)
        else:
            audio = _post_tts(payload, key)
        return {"bytes": audio, "digest": digest, "payload": payload}


def _require_eleven_key(settings: Settings) -> str:
    if not settings.elevenlabs_key_configured():
        raise MissingApiKeyError("ELEVENLABS_API_KEY is not set.")
    return settings.elevenlabs_api_key.get_secret_value()  # type: ignore[union-attr]


def _post_tts(payload: dict[str, Any], api_key: str) -> bytes:
    from urllib.parse import urlencode

    url = f"{payload['url']}?{urlencode(payload['query'])}"
    import json

    body = json.dumps(payload["json"]).encode("utf-8")
    req = Request(
        url,
        data=body,
        method="POST",
        headers={
            "xi-api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "audio/wav",
        },
    )
    with urlopen(req, timeout=120) as resp:  # noqa: S310
        return resp.read()


def write_canonical_wav(raw: bytes, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(raw)
