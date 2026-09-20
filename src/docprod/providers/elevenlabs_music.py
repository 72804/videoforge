from __future__ import annotations

from typing import Any
from urllib.request import Request, urlopen

from docprod.config import Settings, get_settings, require_paid_call_allowed
from docprod.exceptions import MissingApiKeyError
from docprod.providers.paid_cache import PaidArtifactCache, music_cache_hash
from docprod.providers.pricing import ELEVEN_MUSIC_USD_PER_MINUTE, PRICING_AS_OF
from docprod.quality.enums import CostConfidence, PriceMode
from docprod.quality.specs import PricingSpec

MUSIC_URL = "https://api.elevenlabs.io/v1/music"
MUSIC_MODEL = "music_v1"
PRICING = PricingSpec(
    mode=PriceMode.PER_MINUTE,
    value=ELEVEN_MUSIC_USD_PER_MINUTE,
    unit="minute",
    notes="$0.15 per minute of Eleven Music",
    confidence=CostConfidence.KNOWN,
    pricing_as_of=PRICING_AS_OF,
    source_note="https://elevenlabs.io/pricing/api",
)


def build_music_payload(
    *,
    prompt: str,
    duration_seconds: float,
    force_instrumental: bool = True,
    model_id: str = MUSIC_MODEL,
) -> dict[str, Any]:
    length_ms = int(round(duration_seconds * 1000))
    if length_ms < 3000 or length_ms > 600000:
        raise ValueError("Eleven Music music_length_ms must be in [3000, 600000]")
    body = {
        "prompt": prompt,
        "music_length_ms": length_ms,
        "model_id": model_id,
        "force_instrumental": force_instrumental,
    }
    return {
        "url": MUSIC_URL,
        "json": body,
        "estimated_usd": round((duration_seconds / 60.0) * ELEVEN_MUSIC_USD_PER_MINUTE, 6),
    }


class ElevenLabsMusicProvider:
    """POST /v1/music with prompt + music_length_ms. Reference audio only via composition_plan."""

    def __init__(self, *, settings: Settings | None = None, transport: Any | None = None) -> None:
        self.settings = settings or get_settings()
        self.transport = transport

    def compose(
        self,
        prompt: str,
        *,
        duration_seconds: float,
        confirm_paid: bool,
        dry_run: bool = True,
        use_cache: bool = True,
    ) -> dict[str, Any]:
        payload = build_music_payload(prompt=prompt, duration_seconds=duration_seconds)
        digest = music_cache_hash(
            model=MUSIC_MODEL,
            prompt=prompt,
            reference_audio_sha256s=[],
            image_sha256s=[],
            duration_hint_seconds=duration_seconds,
            options={"force_instrumental": True},
        )
        if use_cache:
            hit = PaidArtifactCache().get("music", digest)
            if hit is not None:
                path, meta = hit
                return {"cached": True, "path": str(path), "digest": digest, "meta": meta}
        if dry_run:
            return {"dry_run": True, "digest": digest, "payload": payload, "paid_calls": 0}
        require_paid_call_allowed("elevenlabs", confirm_paid=confirm_paid, settings=self.settings)
        if not self.settings.elevenlabs_key_configured():
            raise MissingApiKeyError("ELEVENLABS_API_KEY is not set.")
        key = self.settings.elevenlabs_api_key.get_secret_value()  # type: ignore[union-attr]
        if self.transport is not None:
            audio = self.transport(payload, key)
        else:
            audio = _post(payload, key)
        return {"bytes": audio, "digest": digest}


def _post(payload: dict[str, Any], api_key: str) -> bytes:
    import json

    req = Request(
        payload["url"],
        data=json.dumps(payload["json"]).encode("utf-8"),
        method="POST",
        headers={"xi-api-key": api_key, "Content-Type": "application/json"},
    )
    with urlopen(req, timeout=180) as resp:  # noqa: S310
        return resp.read()
