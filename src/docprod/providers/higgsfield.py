from __future__ import annotations

from pathlib import Path
from typing import Any

from docprod.config import Settings, get_settings, require_paid_call_allowed
from docprod.exceptions import DocumentedUnimplementedError, MissingApiKeyError
from docprod.providers.paid_cache import video_cache_hash
from docprod.quality.shots import PerformanceShotRequest
from docprod.storage.hashing import file_sha256

# Product constraints from https://higgsfield.ai/genjutsu (not a REST schema).
GENJUTSU_MIN_SECONDS = 3
GENJUTSU_MAX_SECONDS = 30
GENJUTSU_MAX_REFS = 30
GENJUTSU_REASON = (
    "Higgsfield Genjutsu Motion Transfer is documented as a product "
    "(driving video 3–30s, up to 30 reference photos, up to 1080p) at "
    "https://higgsfield.ai/genjutsu, but docs.higgsfield.ai does not publish "
    "a request body or endpoint. Adapter stays DOCUMENTED_UNIMPLEMENTED."
)
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
    cfg = settings or get_settings()
    ident = ""
    if cfg.higgsfield_api_key_id:
        ident = cfg.higgsfield_api_key_id.get_secret_value().strip()
    secret = (
        cfg.higgsfield_api_key_secret.get_secret_value() if cfg.higgsfield_api_key_secret else ""
    ).strip()
    combined = (
        cfg.higgsfield_api_key.get_secret_value() if cfg.higgsfield_api_key else ""
    ).strip()
    if ident and secret:
        return f"Key {ident}:{secret}"
    if combined and ":" in combined:
        return f"Key {combined}"
    raise MissingApiKeyError(
        "Set HIGGSFIELD_API_KEY_ID and HIGGSFIELD_API_KEY_SECRET "
        "(or HIGGSFIELD_API_KEY as id:secret)."
    )


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
