from __future__ import annotations

from pathlib import Path
from typing import Any

from docprod.config import (
    Settings,
    require_paid_call_allowed,
    resolve_higgsfield_api_key,
)
from docprod.exceptions import DocumentedUnimplementedError, MissingApiKeyError
from docprod.providers.paid_cache import video_cache_hash
from docprod.quality.shots import PerformanceShotRequest
from docprod.storage.hashing import file_sha256

# Product constraints from https://higgsfield.ai/genjutsu (not a REST schema).
GENJUTSU_MIN_SECONDS = 1
GENJUTSU_MAX_SECONDS = 30
GENJUTSU_MAX_REFS = 30
GENJUTSU_REASON = (
    "Higgsfield Genjutsu Motion Transfer has a documented subscribe path "
    "higgsfield/genjutsu/motion-transfer/v1.0 (prompt, video_url, image_urls, resolution) "
    "on open.higgsfield.ai. docs.higgsfield.ai still points integrators to console "
    "for per-model schemas. Product adapter does not POST; CATALOG_ONLY contract only."
)
SEEDANCE_CONTRACTS: dict[str, dict[str, object]] = {
    "seedance-2.5-text-to-video": {
        "gateway_model_id": "bytedance/seedance-2.5/text-to-video",
        "url": "https://api.higgsfield.ai/bytedance/seedance-2.5/text-to-video",
        "fields": (
            "prompt",
            "duration",
            "resolution",
            "aspect_ratio",
            "output_format",
            "generate_audio",
        ),
    },
    "seedance-2.5-image-to-video": {
        "gateway_model_id": "bytedance/seedance-2.5/image-to-video",
        "url": "https://api.higgsfield.ai/bytedance/seedance-2.5/image-to-video",
        "fields": (
            "prompt",
            "duration",
            "image_url",
            "resolution",
            "end_image_url",
            "output_format",
            "generate_audio",
        ),
    },
    "seedance-2.5-reference-to-video": {
        "gateway_model_id": "bytedance/seedance-2.5/reference-to-video",
        "url": "https://api.higgsfield.ai/bytedance/seedance-2.5/reference-to-video",
        "fields": (
            "prompt",
            "duration",
            "image_urls",
            "video_urls",
            "audio_urls",
            "resolution",
            "aspect_ratio",
            "bitrate_mode",
            "generate_audio",
        ),
    },
    "seedance-2.5-video-edit": {
        "gateway_model_id": "bytedance/seedance-2.5/video-edit",
        "url": "https://api.higgsfield.ai/bytedance/seedance-2.5/video-edit",
        "fields": ("prompt", "video_url", "resolution", "bitrate_mode", "generate_audio"),
    },
    "seedance-2.5-video-extend": {
        "gateway_model_id": "bytedance/seedance-2.5/video-extend",
        "url": "https://api.higgsfield.ai/bytedance/seedance-2.5/video-extend",
        "fields": (
            "prompt",
            "duration",
            "video_url",
            "resolution",
            "bitrate_mode",
            "generate_audio",
        ),
    },
}
KLING_I2V_CONTRACT = {
    "gateway_model_id": "kling-video/v3.0/pro/image-to-video",
    "url": "https://api.higgsfield.ai/kling-video/v3.0/pro/image-to-video",
    "fields": (
        "prompt",
        "image_url",
        "last_image_url",
        "sound",
        "duration",
    ),
}
KLING_MOTION_CONTRACT = {
    "gateway_model_id": "kling-video/v3/motion-control/pro",
    "url": "https://api.higgsfield.ai/kling-video/v3/motion-control/pro",
    "fields": (
        "prompt",
        "image_url",
        "video_url",
        "keep_original_sound",
        "character_orientation",
    ),
}
SEEDANCE_I2V_REASON = (
    "Official Higgsfield blog documents Seedance 2.0 text-to-video at "
    "https://api.higgsfield.ai/bytedance/seedance-2.0/text-to-video "
    "(prompt, resolution, generate_audio, duration, aspect_ratio). "
    "Image-to-video / character-reference schema is not in the public docs index."
)
KLING_I2V_REASON = (
    "Official docs.higgsfield.ai tells integrators to open console.higgsfield.ai "
    "for per-model schemas. No Kling image-to-video request body is listed in "
    "the public docs index; third-party mirrors are not used."
)


def higgsfield_auth_header(settings: Settings | None = None) -> str:
    key = resolve_higgsfield_api_key(settings)
    if not key:
        raise MissingApiKeyError(
            "Set HF_API_KEY (complete key), or legacy HIGGSFIELD_API_KEY_ID "
            "and HIGGSFIELD_API_KEY_SECRET."
        )
    return f"Key {key}"


def preflight_genjutsu(
    *,
    driving_video: Path | None,
    duration: float,
    reference_count: int,
    dry_run: bool = True,
) -> list[str]:
    errors: list[str] = []
    if duration < GENJUTSU_MIN_SECONDS or duration > GENJUTSU_MAX_SECONDS:
        errors.append(
            f"driving duration {duration}s outside product range "
            f"{GENJUTSU_MIN_SECONDS}–{GENJUTSU_MAX_SECONDS}s"
        )
    if reference_count > GENJUTSU_MAX_REFS:
        errors.append(f"at most {GENJUTSU_MAX_REFS} reference photos")
    if not dry_run and (driving_video is None or not driving_video.is_file()):
        errors.append("driving video file missing")
    return errors


def genjutsu_cache_hash(
    *,
    driving_sha: str,
    ref_shas: list[str],
    audio_sha: str,
    duration: float,
    resolution: str,
    config: dict[str, Any],
) -> str:
    return video_cache_hash(
        model="higgsfield-genjutsu",
        prompt=str(config.get("prompt") or ""),
        negative_prompt="",
        input_image_sha256s=[],
        reference_image_sha256s=ref_shas,
        driving_video_sha256=driving_sha,
        audio_sha256=audio_sha,
        duration_seconds=duration,
        resolution=resolution,
        aspect_ratio=str(config.get("aspect_ratio") or "16:9"),
        seed=config.get("seed"),
    )


class HiggsfieldGenjutsuAdapter:
    def plan(self, request: PerformanceShotRequest, *, dry_run: bool = True) -> dict[str, Any]:
        driving = Path(request.driving_video) if request.driving_video else None
        errors = preflight_genjutsu(
            driving_video=driving,
            duration=request.shot_duration,
            reference_count=len(request.character_refs) + len(request.location_refs),
            dry_run=dry_run,
        )
        digest = genjutsu_cache_hash(
            driving_sha=file_sha256(driving) if driving and driving.is_file() else "",
            ref_shas=[],
            audio_sha="",
            duration=request.shot_duration,
            resolution="1080p",
            config={
                "camera_preservation": request.camera_preservation,
                "motion_preservation": request.motion_preservation,
            },
        )
        return {
            "dry_run": True,
            "adapter_status": "documented_unimplemented",
            "reason": GENJUTSU_REASON,
            "preflight_errors": errors,
            "digest": digest,
            "estimated_usd": None,
            "paid_calls": 0,
        }

    def generate(
        self,
        request: PerformanceShotRequest,
        *,
        confirm_paid: bool,
        dry_run: bool = True,
        settings: Settings | None = None,
    ) -> dict[str, Any]:
        planned = self.plan(request, dry_run=dry_run)
        if planned["preflight_errors"] and not dry_run:
            raise ValueError("; ".join(planned["preflight_errors"]))
        if dry_run:
            return planned
        require_paid_call_allowed("higgsfield", confirm_paid=confirm_paid, settings=settings)
        raise DocumentedUnimplementedError("higgsfield-genjutsu", GENJUTSU_REASON)


class HiggsfieldKlingAdapter:
    def generate_video(self, **_kwargs: object) -> None:
        raise DocumentedUnimplementedError("kling-3", KLING_I2V_REASON)

    def plan_motion_control(self) -> dict[str, Any]:
        return {
            "dry_run": True,
            "adapter_status": "catalog_only",
            "paid_calls": 0,
            "contract": KLING_MOTION_CONTRACT,
        }


def documented_higgsfield_plan(model_id: str) -> dict[str, Any]:
    contract = SEEDANCE_CONTRACTS.get(model_id)
    if model_id == "kling-3.0-motion-control-pro":
        contract = KLING_MOTION_CONTRACT
    if model_id == "kling-3.0-pro-image-to-video":
        contract = KLING_I2V_CONTRACT
    if contract is None:
        raise DocumentedUnimplementedError(model_id, "No documented Higgsfield contract recorded.")
    return {
        "dry_run": True,
        "adapter_status": "catalog_only",
        "paid_calls": 0,
        "model_id": model_id,
        "provider": "higgsfield",
        "vendor": "bytedance" if model_id.startswith("seedance") else "kling",
        "contract": contract,
    }


class HiggsfieldCatalogAdapter:
    """Records official subscribe paths. Never opens HTTP."""

    def plan(self, model_id: str) -> dict[str, Any]:
        return documented_higgsfield_plan(model_id)

    def generate(
        self,
        model_id: str,
        *,
        confirm_paid: bool,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        planned = self.plan(model_id)
        if dry_run:
            return planned
        require_paid_call_allowed("higgsfield", confirm_paid=confirm_paid)
        raise DocumentedUnimplementedError(
            model_id,
            "Higgsfield HTTP is not implemented this phase; catalog contract only.",
        )


def higgsfield_credentials_present(settings: Settings | None = None) -> bool:
    return bool(resolve_higgsfield_api_key(settings))


def seedance_reference_to_video_body(
    *,
    prompt: str,
    duration: float,
    image_urls: list[str],
    audio_urls: list[str] | None = None,
    video_urls: list[str] | None = None,
    resolution: str = "720p",
    aspect_ratio: str = "9:16",
    generate_audio: bool = True,
) -> dict[str, Any]:
    if resolution != "720p":
        raise ValueError("Friend Group Seedance requests must use 720p")
    if aspect_ratio != "9:16":
        raise ValueError("Friend Group Seedance requests must use 9:16")
    seconds = max(4, min(30, int(round(duration))))
    body: dict[str, Any] = {
        "prompt": prompt,
        "duration": seconds,
        "image_urls": list(image_urls),
        "resolution": resolution,
        "aspect_ratio": aspect_ratio,
        "generate_audio": generate_audio,
    }
    if audio_urls:
        body["audio_urls"] = list(audio_urls)
    if video_urls:
        body["video_urls"] = list(video_urls)
    return body


def kling_image_to_video_body(
    *,
    prompt: str,
    image_url: str,
    duration: float,
    last_image_url: str | None = None,
    sound: bool = True,
) -> dict[str, Any]:
    seconds = max(3, min(15, int(round(duration))))
    body: dict[str, Any] = {
        "prompt": prompt,
        "image_url": image_url,
        "duration": seconds,
        "sound": sound,
    }
    if last_image_url:
        body["last_image_url"] = last_image_url
    return body


def kling_motion_control_body(
    *,
    prompt: str,
    image_url: str,
    video_url: str,
    keep_original_sound: bool = False,
) -> dict[str, Any]:
    return {
        "prompt": prompt,
        "image_url": image_url,
        "video_url": video_url,
        "keep_original_sound": keep_original_sound,
        "character_orientation": "image",
    }


def seedance_request_fingerprint(
    *,
    prompt: str,
    duration: float,
    image_shas: list[str],
    audio_shas: list[str],
    resolution: str = "720p",
    aspect_ratio: str = "9:16",
) -> str:
    return video_cache_hash(
        model="seedance-2.5-reference-to-video",
        prompt=prompt,
        negative_prompt="",
        input_image_sha256s=[],
        reference_image_sha256s=image_shas,
        driving_video_sha256="",
        audio_sha256="|".join(audio_shas),
        duration_seconds=float(duration),
        resolution=resolution,
        aspect_ratio=aspect_ratio,
        seed=None,
    )


HIGGSFIELD_API_BASE = "https://api.higgsfield.ai"


def higgsfield_request_status(
    request_id: str,
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """GET existing request status. Never creates a generation."""
    import httpx

    rid = request_id.strip()
    url = f"{HIGGSFIELD_API_BASE}/requests/{rid}/status"
    headers = {"Authorization": higgsfield_auth_header(settings)}
    with httpx.Client(timeout=60.0) as client:
        response = client.get(url, headers=headers)
        response.raise_for_status()
        payload = response.json() if response.content else {}
    return payload if isinstance(payload, dict) else {"raw": payload}


def higgsfield_request_result(
    request_id: str,
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """GET existing request result. Never creates a generation."""
    import httpx

    rid = request_id.strip()
    url = f"{HIGGSFIELD_API_BASE}/requests/{rid}"
    headers = {"Authorization": higgsfield_auth_header(settings)}
    with httpx.Client(timeout=60.0) as client:
        response = client.get(url, headers=headers)
        if response.status_code == 404:
            return {}
        response.raise_for_status()
        payload = response.json() if response.content else {}
    return payload if isinstance(payload, dict) else {"raw": payload}


def extract_higgsfield_video_url(payload: dict[str, Any]) -> str:
    video = payload.get("video")
    if isinstance(video, dict):
        url = str(video.get("url") or "").strip()
        if url:
            return url
    for key in ("images", "audios", "outputs"):
        rows = payload.get(key)
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                url = str(row.get("url") or "").strip()
                if url:
                    return url
    direct = str(payload.get("url") or "").strip()
    if direct.startswith("http"):
        return direct
    for nested_key in ("data", "result", "output", "request"):
        nested = payload.get(nested_key)
        if isinstance(nested, dict):
            found = extract_higgsfield_video_url(nested)
            if found:
                return found
    return ""


def classify_higgsfield_status(raw: str) -> str:
    token = raw.strip().lower().replace(" ", "_")
    if token in {"queued", "pending", "waiting"}:
        return "queued"
    if token in {"in_progress", "processing", "running"}:
        return "in_progress"
    if token in {"completed", "succeeded", "success", "done"}:
        return "completed"
    if token in {"failed", "nsfw", "error"}:
        return "failed"
    if token in {"canceled", "cancelled"}:
        return "canceled"
    return "unknown"


def download_higgsfield_media(url: str, dest: Path) -> Path:
    import httpx

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with httpx.Client(timeout=180.0, follow_redirects=True) as client:
        with client.stream("GET", url) as response:
            response.raise_for_status()
            with tmp.open("wb") as handle:
                for chunk in response.iter_bytes():
                    handle.write(chunk)
    tmp.replace(dest)
    return dest


def submit_higgsfield_json(
    *,
    url: str,
    body: dict[str, Any],
    confirm_paid: bool,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Live POST. Callers must pass confirm_paid and must not invoke this from plan stages."""
    require_paid_call_allowed("higgsfield", confirm_paid=confirm_paid, settings=settings)
    import httpx

    headers = {
        "Authorization": higgsfield_auth_header(settings),
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=120.0) as client:
        response = client.post(url, headers=headers, json=body)
        response.raise_for_status()
        payload = response.json() if response.content else {}
    request_id = ""
    if isinstance(payload, dict):
        request_id = str(payload.get("id") or payload.get("request_id") or "")
    return {"request_id": request_id, "raw": payload}
