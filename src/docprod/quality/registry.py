from __future__ import annotations

from docprod.quality.catalog import get_model
from docprod.quality.enums import (
    AdapterStatus,
    CapabilityMaturity,
    ModelReadiness,
)


def capability_maturity(model_id: str, capability: str) -> CapabilityMaturity:
    spec = get_model(model_id)
    if spec is None:
        return CapabilityMaturity.CATALOG_CAPABILITY
    if capability in spec.tested_capabilities:
        return CapabilityMaturity.TESTED_CAPABILITY
    if capability in spec.implemented_capabilities:
        return CapabilityMaturity.IMPLEMENTED_CAPABILITY
    return CapabilityMaturity.CATALOG_CAPABILITY


def auto_route_allowed(model_id: str) -> bool:
    """Catalog-only models never become customer auto-routes."""
    if model_id in {"local-camera", "local-title", "narration-over-image"}:
        return True
    spec = get_model(model_id)
    if spec is None:
        return False
    if spec.adapter_status is AdapterStatus.DOCUMENTED_UNIMPLEMENTED:
        return False
    if spec.readiness is ModelReadiness.CATALOG_ONLY:
        return False
    if spec.readiness is ModelReadiness.INTERNAL_CANARY:
        return False
    if spec.local:
        return True
    return bool(spec.implemented) and spec.readiness in {
        ModelReadiness.ADAPTER_IMPLEMENTED,
        ModelReadiness.PRODUCTION_READY,
    }


def eligible_models_for(
    capability: str,
    *,
    auto_only: bool = True,
) -> list[str]:
    from docprod.quality.catalog import model_catalog

    out: list[str] = []
    for spec in model_catalog():
        caps = set(spec.capabilities) | set(spec.catalog_capabilities)
        if capability not in caps:
            continue
        if auto_only and not auto_route_allowed(spec.model_id):
            continue
        out.append(spec.model_id)
    return out
