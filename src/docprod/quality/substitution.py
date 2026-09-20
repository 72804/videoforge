from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from docprod.models.scene import Scene
from docprod.quality.duration import trim_to_scene_window
from docprod.storage.paths import ProjectPaths

V1_EPISODE = "birko_kemal_drama_v1.mp4"
V2_EPISODE = "birko_kemal_drama_v2.mp4"


def upgrade_clip_path(paths: ProjectPaths, scene_id: str) -> Path:
    return paths.visuals_dir / "upgrades" / f"{scene_id}.mp4"


def episode_output_name(*, version: int) -> str:
    if version <= 1:
        return V1_EPISODE
    return V2_EPISODE


@dataclass(frozen=True)
class SubstitutionPlan:
    scene_id: str
    source: Path
    used_seconds: float
    clip_seconds: float
    trim_to: float
    timing_unchanged: bool = True


def plan_substitution(
    scene: Scene, clip_duration: float, *, source: Path | None = None
) -> SubstitutionPlan:
    trim = trim_to_scene_window(clip_duration, scene.duration)
    return SubstitutionPlan(
        scene_id=scene.id,
        source=source or Path(f"{scene.id}.mp4"),
        used_seconds=scene.duration,
        clip_seconds=clip_duration,
        trim_to=trim,
        timing_unchanged=True,
    )
