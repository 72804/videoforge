from __future__ import annotations

from dataclasses import dataclass

from docprod.product.enums import ModelCapability
from docprod.quality.enums import QualityTier


@dataclass(frozen=True)
class CustomerModel:
    internal_id: str
    display_name: str
    provider: str
    capability: ModelCapability
    quality_tier: QualityTier
    availability: str
    engine_model_id: str
    stars_per_unit: int
    provider_usd_per_unit: float
    unit: str


def telegram_model_catalog() -> tuple[CustomerModel, ...]:
    """Customer-facing catalog. Engine IDs stay internal."""
    return (
        CustomerModel(
            internal_id="auto-text",
            display_name="Auto",
            provider="router",
            capability=ModelCapability.AUTO,
            quality_tier=QualityTier.STANDARD,
            availability="available",
            engine_model_id="auto",
            stars_per_unit=0,
            provider_usd_per_unit=0.0,
            unit="job",
        ),
        CustomerModel(
            internal_id="auto-image",
            display_name="Auto",
            provider="router",
            capability=ModelCapability.IMAGE,
            quality_tier=QualityTier.STANDARD,
            availability="available",
            engine_model_id="auto",
            stars_per_unit=8,
            provider_usd_per_unit=0.05,
            unit="image",
        ),
        CustomerModel(
            internal_id="auto-video",
            display_name="Auto",
            provider="router",
            capability=ModelCapability.VIDEO,
            quality_tier=QualityTier.STANDARD,
            availability="available",
            engine_model_id="auto",
            stars_per_unit=40,
            provider_usd_per_unit=0.40,
            unit="clip",
        ),
        CustomerModel(
            internal_id="veo-lite",
            display_name="Veo Lite",
            provider="google",
            capability=ModelCapability.VIDEO,
            quality_tier=QualityTier.STANDARD,
            availability="available",
            engine_model_id="veo-3.1-lite-generate-preview",
            stars_per_unit=40,
            provider_usd_per_unit=0.40,
            unit="8s",
        ),
        CustomerModel(
            internal_id="veo-quality",
            display_name="Veo Quality",
            provider="google",
            capability=ModelCapability.VIDEO,
            quality_tier=QualityTier.PREMIUM,
            availability="planned",
            engine_model_id="veo-3.1-generate-preview",
            stars_per_unit=120,
            provider_usd_per_unit=1.20,
            unit="8s",
        ),
        CustomerModel(
            internal_id="image-standard",
            display_name="Image Standard",
            provider="openai",
            capability=ModelCapability.IMAGE,
            quality_tier=QualityTier.STANDARD,
            availability="available",
            engine_model_id="gpt-image-2.5-flare",
            stars_per_unit=8,
            provider_usd_per_unit=0.05,
            unit="image",
        ),
    )


def resolve_customer_model(internal_id: str) -> CustomerModel:
    for item in telegram_model_catalog():
        if item.internal_id == internal_id:
            return item
    raise KeyError(f"unknown customer model {internal_id}")
