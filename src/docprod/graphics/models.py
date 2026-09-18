from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from docprod.graphics import GRAPHIC_HEIGHT, GRAPHIC_RENDERER_VERSION, GRAPHIC_WIDTH


class GraphicManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    scene_id: str
    graphic_type: str
    renderer_version: str = GRAPHIC_RENDERER_VERSION
    source_scene_hash: str
    request_hash: str
    output_sha256: str
    output_path: str
    text_fields: dict[str, str] = Field(default_factory=dict)
    layout_variant: str
    font: str
    width: int = GRAPHIC_WIDTH
    height: int = GRAPHIC_HEIGHT
    cache_hit: bool = False
    elapsed_seconds: float | None = None
    extra: dict[str, Any] = Field(default_factory=dict)
