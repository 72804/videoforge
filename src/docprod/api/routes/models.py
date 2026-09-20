from __future__ import annotations

from fastapi import APIRouter

from docprod.api.schemas import ModelView
from docprod.product.catalog import telegram_model_catalog

router = APIRouter(tags=["models"])


@router.get("/models", response_model=list[ModelView], operation_id="listModels")
def list_models() -> list[ModelView]:
    rows = [
        ModelView(
            id="auto",
            display_name="Auto",
            capabilities=["text", "image", "video"],
            quality_tier="standard",
            available=True,
        )
    ]
    for item in telegram_model_catalog():
        if item.internal_id.startswith("auto"):
            continue
        rows.append(
            ModelView(
                id=item.internal_id,
                display_name=item.display_name,
                capabilities=[item.capability.value],
                quality_tier=item.quality_tier.value,
                available=item.availability == "available",
            )
        )
    return rows
