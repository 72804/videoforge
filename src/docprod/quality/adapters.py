from __future__ import annotations

from docprod.exceptions import UnimplementedProviderError
from docprod.quality.catalog import get_model
from docprod.quality.enums import ProviderStatus
from docprod.quality.specs import DialogueShotRequest, PerformanceShotRequest


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

    def generate_video(self, **_kwargs: object) -> None:
        raise UnimplementedProviderError(
            f"{self.model_id} has no implemented network adapter in this phase."
        )

    def generate_dialogue(self, request: DialogueShotRequest) -> None:
        _ = request
        raise UnimplementedProviderError(
            f"{self.model_id} dialogue adapter is unimplemented (dry-run only)."
        )

    def generate_performance(self, request: PerformanceShotRequest) -> None:
        _ = request
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
