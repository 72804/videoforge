from __future__ import annotations

import base64
import json
import mimetypes
import time
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
from docprod.providers.veo_journal import (
    CACHE_COMMITTED,
    DOWNLOAD_FAILED,
    DOWNLOAD_SUCCEEDED,
    DOWNLOADABLE_STATES,
    GENERATION_IN_PROGRESS,
    GENERATION_SUCCEEDED_REMOTE,
    REQUEST_SUBMITTED,
    load_journal,
    write_journal,
)
from docprod.quality.duration import billable_seconds
from docprod.quality.enums import CostConfidence, PriceMode
from docprod.quality.specs import DialogueShotRequest, PerformanceShotRequest, PricingSpec
from docprod.storage.hashing import file_sha256
from docprod.storage.identity import poll_delays

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


def image_data_uri(path: Path) -> str:
    mime, _ = mimetypes.guess_type(path.name)
    if mime not in {"image/jpeg", "image/png", "image/webp"}:
        suffix = path.suffix.lower()
        mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}.get(
            suffix, "image/jpeg"
        )
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


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
        image_uri = f"file:{image_path}" if dry_run else image_data_uri(image_path)
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
        cache = PaidArtifactCache()
        if use_cache:
            hit = cache.get(kind, digest)
            if hit is not None:
                path, meta = hit
                return {
                    "cached": True,
                    "path": str(path),
                    "digest": digest,
                    "meta": meta,
                    "paid_calls": 0,
                }
        if dry_run:
            return {"dry_run": True, "digest": digest, "payload": payload, "paid_calls": 0}
        require_paid_call_allowed("runway", confirm_paid=confirm_paid, settings=self.settings)
        key = _runway_key(self.settings)
        if self.transport is not None:
            return {"remote": self.transport(payload, key), "digest": digest, "paid_calls": 1}
        return _live_image_to_video(
            cache=cache,
            kind=kind,
            digest=digest,
            payload=payload,
            api_key=key,
            use_cache=use_cache,
        )


def _runway_key(settings: Settings) -> str:
    if not settings.runway_key_configured():
        raise MissingApiKeyError("RUNWAY_API_KEY is not set.")
    return settings.runway_api_key.get_secret_value()  # type: ignore[union-attr]


def _headers(api_key: str, *, json_body: bool = False) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "X-Runway-Version": RUNWAY_VERSION,
    }
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers


def _post(payload: dict[str, Any], api_key: str) -> dict[str, Any]:
    req = Request(
        payload["url"],
        data=json.dumps(payload["json"]).encode("utf-8"),
        method="POST",
        headers=_headers(api_key, json_body=True),
    )
    with urlopen(req, timeout=60) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


def _get_task(task_id: str, api_key: str) -> dict[str, Any]:
    req = Request(
        f"{RUNWAY_BASE}/v1/tasks/{task_id}",
        method="GET",
        headers=_headers(api_key),
    )
    with urlopen(req, timeout=60) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


def _download_bytes(url: str) -> bytes:
    req = Request(url, method="GET")
    with urlopen(req, timeout=180) as resp:  # noqa: S310
        payload = resp.read()
    if not payload:
        raise RuntimeError("Runway download produced no bytes")
    return payload


def _task_output_url(task: dict[str, Any]) -> str:
    output = task.get("output")
    if isinstance(output, list) and output:
        first = output[0]
        if isinstance(first, str) and first.startswith("http"):
            return first
        if isinstance(first, dict):
            for key in ("url", "uri", "href"):
                value = first.get(key)
                if isinstance(value, str) and value.startswith("http"):
                    return value
    if isinstance(output, str) and output.startswith("http"):
        return output
    raise RuntimeError("Runway task succeeded but no downloadable output URL was present")


def _live_image_to_video(
    *,
    cache: PaidArtifactCache,
    kind: str,
    digest: str,
    payload: dict[str, Any],
    api_key: str,
    use_cache: bool,
) -> dict[str, Any]:
    journal = load_journal(cache.root, digest) if use_cache else None
    if journal and journal.get("state") in DOWNLOADABLE_STATES:
        task_id = str(journal.get("task_id") or "")
        if not task_id:
            raise RuntimeError(
                "Runway journal is downloadable but missing task_id; billing state unknown — STOP"
            )
        task = _get_task(task_id, api_key)
        return _commit_runway_task(
            cache=cache,
            kind=kind,
            digest=digest,
            payload=payload,
            task=task,
            billed_this_run=False,
            recovered=True,
        )
    if journal and str(journal.get("task_id") or ""):
        task_id = str(journal["task_id"])
        status = str(journal.get("state") or "")
        if status in {REQUEST_SUBMITTED, GENERATION_IN_PROGRESS}:
            task = _poll_task(task_id, api_key, digest=digest, cache_root=cache.root)
            return _commit_runway_task(
                cache=cache,
                kind=kind,
                digest=digest,
                payload=payload,
                task=task,
                billed_this_run=False,
                recovered=True,
            )
        raise RuntimeError(
            f"Runway journal state {status!r} is ambiguous; will not resubmit — STOP"
        )
    remote = _post(payload, api_key)
    task_id = str(remote.get("id") or "")
    if not task_id:
        raise RuntimeError("Runway POST returned no task id; billing state unknown — STOP")
    write_journal(
        cache.root,
        digest,
        {
            "provider": "runway",
            "model": GEN45_MODEL,
            "task_id": task_id,
            "state": REQUEST_SUBMITTED,
            "estimated_usd": payload.get("estimated_usd"),
        },
    )
    task = _poll_task(task_id, api_key, digest=digest, cache_root=cache.root)
    return _commit_runway_task(
        cache=cache,
        kind=kind,
        digest=digest,
        payload=payload,
        task=task,
        billed_this_run=True,
        recovered=False,
    )


def _poll_task(task_id: str, api_key: str, *, digest: str, cache_root: Path) -> dict[str, Any]:
    task: dict[str, Any] = {"id": task_id, "status": "PENDING"}
    for delay in poll_delays():
        task = _get_task(task_id, api_key)
        status = str(task.get("status") or "").upper()
        write_journal(
            cache_root,
            digest,
            {
                **(load_journal(cache_root, digest) or {}),
                "provider": "runway",
                "task_id": task_id,
                "state": GENERATION_IN_PROGRESS,
                "remote_status": status,
            },
        )
        if status in {"SUCCEEDED", "SUCCESS", "COMPLETED"}:
            write_journal(
                cache_root,
                digest,
                {
                    **(load_journal(cache_root, digest) or {}),
                    "state": GENERATION_SUCCEEDED_REMOTE,
                    "task_id": task_id,
                },
            )
            return task
        if status in {"FAILED", "CANCELLED", "CANCELED", "ERROR"}:
            raise RuntimeError(f"Runway task {task_id} failed with status {status}")
        time.sleep(delay)
    raise RuntimeError(
        f"Runway task {task_id} timed out; do not resubmit — inspect remote task first"
    )


def _commit_runway_task(
    *,
    cache: PaidArtifactCache,
    kind: str,
    digest: str,
    payload: dict[str, Any],
    task: dict[str, Any],
    billed_this_run: bool,
    recovered: bool,
) -> dict[str, Any]:
    status = str(task.get("status") or "").upper()
    if status not in {"SUCCEEDED", "SUCCESS", "COMPLETED"}:
        raise RuntimeError(f"Runway task not successful: {status or 'unknown'}")
    url = _task_output_url(task)
    try:
        blob = _download_bytes(url)
    except Exception:
        prior = load_journal(cache.root, digest) or {}
        write_journal(
            cache.root,
            digest,
            {**prior, "state": DOWNLOAD_FAILED, "output_url": url},
        )
        raise
    write_journal(
        cache.root,
        digest,
        {**(load_journal(cache.root, digest) or {}), "state": DOWNLOAD_SUCCEEDED},
    )
    dest = cache.put(
        kind,
        digest,
        blob,
        suffix=".mp4",
        meta={
            "provider": "runway",
            "model": GEN45_MODEL,
            "estimated_usd": float(payload.get("estimated_usd") or 0),
            "billed_this_run": billed_this_run,
            "recovered": recovered,
        },
    )
    write_journal(
        cache.root,
        digest,
        {**(load_journal(cache.root, digest) or {}), "state": CACHE_COMMITTED},
    )
    return {
        "cached": False,
        "path": str(dest),
        "digest": digest,
        "paid_calls": 1 if billed_this_run else 0,
        "recovered": recovered,
        "estimated_usd": payload.get("estimated_usd"),
    }
