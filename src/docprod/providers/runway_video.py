from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from docprod.config import Settings, get_settings, require_paid_call_allowed
from docprod.exceptions import MissingApiKeyError
from docprod.providers.paid_cache import PaidArtifactCache, video_cache_hash
from docprod.providers.pricing import (
    PRICING_AS_OF,
    RUNWAY_ACT_TWO_USD_PER_SEC,
    RUNWAY_GEN45_USD_PER_SEC,
)
from docprod.quality.duration import billable_seconds
from docprod.quality.enums import CostConfidence, PriceMode
from docprod.quality.specs import DialogueShotRequest, PerformanceShotRequest, PricingSpec
from docprod.storage.hashing import file_sha256

RUNWAY_BASE = "https://api.dev.runwayml.com"
RUNWAY_VERSION = "2024-11-06"
GEN45_MODEL = "gen4.5"
ACT_TWO_MODEL = "act_two"
GEN45_PRICING = PricingSpec(
    mode=PriceMode.PER_SECOND,
    value=RUNWAY_GEN45_USD_PER_SEC,
    unit="second",
    notes="12 credits/s × $0.01/credit",
    confidence=CostConfidence.KNOWN,
    pricing_as_of=PRICING_AS_OF,
    source_note="https://docs.dev.runwayml.com/guides/pricing/",
)
ACT_TWO_PRICING = PricingSpec(
    mode=PriceMode.PER_SECOND,
    value=RUNWAY_ACT_TWO_USD_PER_SEC,
    unit="second",
    notes="5 credits/s × $0.01/credit; driving video 3–30s",
    confidence=CostConfidence.KNOWN,
    pricing_as_of=PRICING_AS_OF,
    source_note="https://docs.dev.runwayml.com/guides/pricing/",
)


def build_gen45_payload(
    *,
    prompt: str,
    image_uri: str,
    duration: int,
    ratio: str = "1280:720",
    seed: int | None = None,
) -> dict[str, Any]:
    if duration < 2 or duration > 10:
        raise ValueError("Runway gen4.5 duration must be an integer 2–10")
    if len(prompt) > 1000:
        raise ValueError("Runway gen4.5 promptText max 1000 characters")
    body: dict[str, Any] = {
        "model": GEN45_MODEL,
        "promptText": prompt,
        "promptImage": image_uri,
        "ratio": ratio,
        "duration": duration,
    }
    if seed is not None:
        body["seed"] = seed
    return {
        "url": f"{RUNWAY_BASE}/v1/image_to_video",
        "json": body,
        "estimated_usd": round(duration * RUNWAY_GEN45_USD_PER_SEC, 6),
    }


def build_act_two_payload(
    *,
    character_image_uri: str,
    driving_video_uri: str,
    body_control: bool = True,
    expression_intensity: int = 3,
    ratio: str = "1280:720",
    seed: int | None = None,
    driving_seconds: float = 5.0,
) -> dict[str, Any]:
    if expression_intensity < 1 or expression_intensity > 5:
        raise ValueError("Act-Two expressionIntensity must be 1–5")
    body: dict[str, Any] = {
        "model": ACT_TWO_MODEL,
        "character": {"type": "image", "uri": character_image_uri},
        "reference": {"type": "video", "uri": driving_video_uri},
        "bodyControl": body_control,
        "expressionIntensity": expression_intensity,
        "ratio": ratio,
    }
    if seed is not None:
        body["seed"] = seed
    billable = billable_seconds("runway-act-two", driving_seconds)
    return {
        "url": f"{RUNWAY_BASE}/v1/character_performance",
        "json": body,
        "estimated_usd": round(billable * RUNWAY_ACT_TWO_USD_PER_SEC, 6),
        "billable_seconds": billable,
    }


def act_two_from_requests(
    dialogue: DialogueShotRequest | None = None,
    performance: PerformanceShotRequest | None = None,
    *,
    character_uri: str,
    driving_uri: str,
) -> dict[str, Any]:
    duration = 5.0
    intensity = 3
    if dialogue is not None:
        duration = dialogue.duration
        if dialogue.emotion in {"chaotic", "tense"}:
            intensity = 4
    if performance is not None:
        duration = performance.shot_duration
    return build_act_two_payload(
        character_image_uri=character_uri,
        driving_video_uri=driving_uri,
        driving_seconds=duration,
        expression_intensity=intensity,
        body_control=True,
    )


class RunwayVideoProvider:
    def __init__(self, *, settings: Settings | None = None, transport: Any | None = None) -> None:
        self.settings = settings or get_settings()
        self.transport = transport

    def generate_image_to_video(
        self,
        *,
        prompt: str,
        image_path: Path,
        duration: int,
        confirm_paid: bool,
        dry_run: bool = True,
        use_cache: bool = True,
    ) -> dict[str, Any]:
        if not image_path.is_file() and not dry_run:
            raise FileNotFoundError(image_path)
        image_uri = f"file:{image_path}" if dry_run else str(image_path)
        payload = build_gen45_payload(prompt=prompt, image_uri=image_uri, duration=duration)
        digest = video_cache_hash(
            model=GEN45_MODEL,
            prompt=prompt,
            negative_prompt="",
            input_image_sha256s=[file_sha256(image_path)] if image_path.is_file() else [""],
            reference_image_sha256s=[],
            driving_video_sha256="",
            audio_sha256="",
            duration_seconds=float(duration),
            resolution="1280:720",
            aspect_ratio="16:9",
        )
        return self._finish("video", digest, payload, confirm_paid, dry_run, use_cache)

    def generate_act_two(
        self,
        *,
        character_image: Path,
        driving_video: Path,
        confirm_paid: bool,
        driving_seconds: float,
        dry_run: bool = True,
        use_cache: bool = True,
        body_control: bool = True,
    ) -> dict[str, Any]:
        if not dry_run:
            if not character_image.is_file():
                raise FileNotFoundError(character_image)
            if not driving_video.is_file():
                raise FileNotFoundError(driving_video)
        payload = build_act_two_payload(
            character_image_uri=f"file:{character_image}",
            driving_video_uri=f"file:{driving_video}",
            driving_seconds=driving_seconds,
            body_control=body_control,
        )
        char_hash = file_sha256(character_image) if character_image.is_file() else ""
        drive_hash = file_sha256(driving_video) if driving_video.is_file() else ""
        digest = video_cache_hash(
            model=ACT_TWO_MODEL,
            prompt="act_two",
            negative_prompt="",
            input_image_sha256s=[char_hash],
            reference_image_sha256s=[],
            driving_video_sha256=drive_hash,
            audio_sha256="",
            duration_seconds=payload["billable_seconds"],
            resolution="1280:720",
            aspect_ratio="16:9",
            seed=None,
        )
        return self._finish("video", digest, payload, confirm_paid, dry_run, use_cache)

    def _finish(
        self,
        kind: str,
        digest: str,
        payload: dict[str, Any],
        confirm_paid: bool,
        dry_run: bool,
        use_cache: bool,
    ) -> dict[str, Any]:
        if use_cache:
            hit = PaidArtifactCache().get(kind, digest)
            if hit is not None:
                path, meta = hit
                return {"cached": True, "path": str(path), "digest": digest, "meta": meta}
        if dry_run:
            return {"dry_run": True, "digest": digest, "payload": payload, "paid_calls": 0}
        require_paid_call_allowed("runway", confirm_paid=confirm_paid, settings=self.settings)
        key = _runway_key(self.settings)
        if self.transport is not None:
            return {"remote": self.transport(payload, key), "digest": digest}
        return {"remote": _post(payload, key), "digest": digest}


def _runway_key(settings: Settings) -> str:
    if not settings.runway_key_configured():
        raise MissingApiKeyError("RUNWAY_API_KEY is not set.")
    return settings.runway_api_key.get_secret_value()  # type: ignore[union-attr]


def _post(payload: dict[str, Any], api_key: str) -> dict[str, Any]:
    req = Request(
        payload["url"],
        data=json.dumps(payload["json"]).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "X-Runway-Version": RUNWAY_VERSION,
            "Content-Type": "application/json",
        },
    )
    with urlopen(req, timeout=60) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))
