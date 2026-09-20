from __future__ import annotations

from typing import Any
from urllib.request import Request, urlopen

from docprod.config import Settings, get_settings, require_paid_call_allowed
from docprod.exceptions import MissingApiKeyError
from docprod.providers.paid_cache import PaidArtifactCache, sfx_cache_hash
from docprod.providers.pricing import ELEVEN_SFX_USD_PER_MINUTE, PRICING_AS_OF
from docprod.quality.enums import CostConfidence, PriceMode
from docprod.quality.specs import PricingSpec

SFX_URL = "https://api.elevenlabs.io/v1/sound-generation"
SFX_MODEL = "eleven_text_to_sound_v2"
PRICING = PricingSpec(
    mode=PriceMode.PER_MINUTE,
    value=ELEVEN_SFX_USD_PER_MINUTE,
    unit="minute",
    notes="$0.12 per minute of generated SFX",
    confidence=CostConfidence.KNOWN,
    pricing_as_of=PRICING_AS_OF,
    source_note="https://elevenlabs.io/pricing/api",
)


def build_sfx_payload(
    *,
    prompt: str,
    duration_seconds: float,
    loop: bool = False,
    prompt_influence: float = 0.3,
) -> dict[str, Any]:
    if duration_seconds < 0.5 or duration_seconds > 30:
        raise ValueError("Eleven SFX duration_seconds must be in [0.5, 30]")
    body = {
        "text": prompt,
        "duration_seconds": duration_seconds,
        "loop": loop,
        "prompt_influence": prompt_influence,
        "model_id": SFX_MODEL,
    }
    return {
        "url": SFX_URL,
        "json": body,
        "estimated_usd": round((duration_seconds / 60.0) * ELEVEN_SFX_USD_PER_MINUTE, 6),
    }


class ElevenLabsSFXProvider:
    def __init__(self, *, settings: Settings | None = None, transport: Any | None = None) -> None:
        self.settings = settings or get_settings()
        self.transport = transport

    def generate(
        self,
        prompt: str,
        *,
        duration_seconds: float,
        confirm_paid: bool,
        loop: bool = False,
        dry_run: bool = True,
        use_cache: bool = True,
    ) -> dict[str, Any]:
        payload = build_sfx_payload(
            prompt=prompt, duration_seconds=duration_seconds, loop=loop
        )
        digest = sfx_cache_hash(
            model=SFX_MODEL,
            prompt=prompt,
            duration=duration_seconds,
            settings={"loop": loop, "prompt_influence": 0.3},
        )
        if use_cache:
            hit = PaidArtifactCache().get("sfx", digest)
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
    with urlopen(req, timeout=120) as resp:  # noqa: S310
        return resp.read()
