from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from docprod.product.ids import new_id


class MotionTemplate(BaseModel):
    """Reusable motion metadata. Library is empty until we curate assets."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_id)
    name: str
    category: str
    source_type: str = "library"
    duration: float = 4.0
    people_count: int = 1
    orientation: str = "9:16"
    energy: str = "medium"
    camera_motion: str = "locked"
    audio_available: bool = False
    rights_source: str = ""
    storage_key: str = ""
    compatible_capabilities: list[str] = Field(
        default_factory=lambda: ["motion_controlled_performance"]
    )


MOTION_TEMPLATE_CATEGORIES: tuple[str, ...] = (
    "argument",
    "door_reveal",
    "awkward_stare",
    "run",
    "dance",
    "celebrate",
    "sit",
    "walk",
    "fight_standoff",
    "phone_reaction",
)


def empty_motion_library() -> list[MotionTemplate]:
    return []
