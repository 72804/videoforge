from __future__ import annotations

from pathlib import Path

from docprod.exceptions import DocumentedUnimplementedError, UnimplementedProviderError
from docprod.providers.higgsfield import HiggsfieldGenjutsuAdapter, HiggsfieldKlingAdapter
from docprod.providers.runway_video import RunwayVideoProvider, act_two_from_requests
from docprod.quality.catalog import get_model
from docprod.quality.duration import billable_seconds
from docprod.quality.enums import AdapterStatus, ProviderStatus
from docprod.quality.specs import (
    AudioDrivenDialogueRequest,
    DialogueShotRequest,
    PerformanceShotRequest,
)


class ProviderAdapter:
    """Capability-driven boundary. generate_* must not guess HTTP contracts."""

    def __init__(self, model_id: str) -> None:
        self.model_id = model_id
        self.spec = get_model(model_id)

    def status(self) -> ProviderStatus:
        if self.spec is None:
            return ProviderStatus.UNCONFIGURED
        if self.spec.implemented:
            return ProviderStatus.CONFIGURED
        return ProviderStatus.UNCONFIGURED

    def adapter_status(self) -> AdapterStatus:
        if self.spec is None:
            return AdapterStatus.CATALOG_ONLY
        return self.spec.adapter_status

    def generate_video(self, **_kwargs: object) -> None:
        if self.model_id in {"kling-3", "kling-2.5-turbo-i2v"}:
            HiggsfieldKlingAdapter().generate_video()
        raise UnimplementedProviderError(
            f"{self.model_id} has no implemented network adapter in this phase."
        )

    def generate_dialogue(self, request: DialogueShotRequest) -> dict[str, object]:
        if self.model_id == "runway-gen-4.5":
            seconds = int(billable_seconds("runway-gen-4.5", request.duration))
            return runway_dry_run_i2v(request.camera_instructions or request.dialogue_text, seconds)
        if self.model_id == "audio-driven-lipsync":
            raise UnimplementedProviderError(
                "audio-driven-lipsync has no documented adapter; implied I2V fallback applies"
            )
        if self.model_id == "runway-act-two":
            if not (request.source_video or "").strip():
                raise UnimplementedProviderError(
                    "Act-Two skipped: no driving video (manual input not required)"
                )
            return act_two_from_requests(
                dialogue=request,
                character_uri=request.source_image or "file:character",
                driving_uri=request.source_video,
            )
        _ = request
        raise UnimplementedProviderError(
            f"{self.model_id} dialogue adapter is unimplemented (dry-run only)."
        )

    def generate_audio_driven(self, request: AudioDrivenDialogueRequest) -> dict[str, object]:
        _ = request
        raise UnimplementedProviderError(
            "No documented audio-driven lipsync adapter; do not guess a payload."
        )

    def generate_performance(self, request: PerformanceShotRequest) -> dict[str, object]:
        if self.model_id == "higgsfield-genjutsu":
            return HiggsfieldGenjutsuAdapter().plan(request, dry_run=True)
        if self.model_id == "runway-act-two":
            if not (request.driving_video or "").strip():
                raise UnimplementedProviderError(
                    "Act-Two skipped: no driving video (manual input not required)"
                )
            refs = request.character_refs
            character_uri = refs[0] if refs else "file:character"
            return act_two_from_requests(
                performance=request,
                character_uri=character_uri,
                driving_uri=request.driving_video or "file:driving",
            )
        raise UnimplementedProviderError(
            f"{self.model_id} performance adapter is unimplemented (dry-run only)."
        )


class MockAdapter(ProviderAdapter):
    """Local tests: records requests, never opens sockets."""

    def __init__(self, model_id: str) -> None:
        super().__init__(model_id)
        self.calls: list[str] = []

    def generate_video(self, **kwargs: object) -> dict[str, object]:
        self.calls.append("video")
        return {"dry_run": True, "model": self.model_id, "kwargs": kwargs}

    def generate_dialogue(self, request: DialogueShotRequest) -> dict[str, object]:
        self.calls.append("dialogue")
        return {"dry_run": True, "scene_id": request.scene_id}

    def generate_performance(self, request: PerformanceShotRequest) -> dict[str, object]:
        self.calls.append("performance")
        return {"dry_run": True, "scene_id": request.scene_id}


def runway_dry_run_i2v(prompt: str, duration: int) -> dict[str, object]:
    return RunwayVideoProvider().generate_image_to_video(
        prompt=prompt,
        image_path=Path("/nonexistent.jpg"),
        duration=duration,
        confirm_paid=False,
        dry_run=True,
        use_cache=False,
    )


def assert_documented_unimplemented(model_id: str) -> None:
    adapter = ProviderAdapter(model_id)
    try:
        adapter.generate_video()
    except DocumentedUnimplementedError:
        return
    raise AssertionError(f"{model_id} should be documented-unimplemented")
