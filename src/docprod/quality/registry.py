from __future__ import annotations

from docprod.quality.catalog import get_model
from docprod.quality.enums import CapabilityMaturity


def capability_maturity(model_id: str, capability: str) -> CapabilityMaturity:
    spec = get_model(model_id)
    if spec is None:
        return CapabilityMaturity.CATALOG_CAPABILITY
    if capability in spec.tested_capabilities:
        return CapabilityMaturity.TESTED_CAPABILITY
    if capability in spec.implemented_capabilities:
        return CapabilityMaturity.IMPLEMENTED_CAPABILITY
    return CapabilityMaturity.CATALOG_CAPABILITY
