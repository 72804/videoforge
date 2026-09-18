from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from docprod.exceptions import UnsafeProjectIdError

PROJECT_ID_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,62}$")

NARRATION_FILENAME = "04_narration.json"
SCENE_PLAN_FILENAME = "05_scenes.json"
SCENE_PLANNER_STAGE = "scene_planner"
PREVIEW_RENDER_STAGE = "preview_render"
RENDERER_VERSION = "1.2"
VISUAL_BIBLE_FILENAME = "visual_bible.json"
IMAGE_REVIEW_FILENAME = "image.review.json"
IMAGE_BATCH_MANIFEST_FILENAME = "image_batch_manifest.json"
CONTACT_SHEET_FILENAME = "contact_sheet.jpg"
CONTACT_SHEET_REPAIRS_FILENAME = "contact_sheet_repairs.jpg"
GRAPHICS_CONTACT_SHEET_FILENAME = "graphics_contact_sheet.jpg"


def default_repo_root() -> Path:
    """Repository root (directory that contains pyproject.toml / projects/)."""
    return Path(__file__).resolve().parents[3]


def default_projects_root() -> Path:
    return default_repo_root() / "projects"


def default_cache_root() -> Path:
    return default_repo_root() / "cache"


def validate_project_id(project_id: str) -> str:
    """Reject IDs that are not filesystem-safe. Do not silently normalize."""
    if not isinstance(project_id, str) or not PROJECT_ID_PATTERN.fullmatch(project_id):
        raise UnsafeProjectIdError(
            f"Unsafe or invalid project id {project_id!r}. "
            "IDs must start with a letter and contain only letters, digits, '_' or '-' "
            "(no path separators or '..')."
        )
    return project_id


@dataclass(frozen=True)
class ProjectPaths:
    root: Path

    @property
    def project_json(self) -> Path:
        return self.root / "project.json"

    @property
    def job_json(self) -> Path:
        return self.root / "job.json"

    @property
    def stages_dir(self) -> Path:
        return self.root / "stages"

    @property
    def artifacts_dir(self) -> Path:
        return self.root / "artifacts"

    @property
    def audio_dir(self) -> Path:
        return self.artifacts_dir / "audio"

    @property
    def visuals_dir(self) -> Path:
        return self.artifacts_dir / "visuals"

    @property
    def subtitles_dir(self) -> Path:
        return self.artifacts_dir / "subtitles"

    @property
    def render_dir(self) -> Path:
        return self.artifacts_dir / "render"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    @property
    def narration_json(self) -> Path:
        return self.stages_dir / NARRATION_FILENAME

    @property
    def scene_plan_json(self) -> Path:
        return self.stages_dir / SCENE_PLAN_FILENAME

    @property
    def preview_dir(self) -> Path:
        return self.render_dir / "preview"

    @property
    def preview_segments_dir(self) -> Path:
        return self.preview_dir / "segments"

    @property
    def preview_debug_dir(self) -> Path:
        return self.preview_dir / "debug"

    @property
    def preview_mp4(self) -> Path:
        return self.preview_dir / "documentary_preview.mp4"

    @property
    def preview_manifest(self) -> Path:
        return self.preview_dir / "render_manifest.json"

    @property
    def captions_srt(self) -> Path:
        return self.preview_dir / "captions.srt"

    @property
    def captions_ass(self) -> Path:
        return self.preview_dir / "captions.ass"

    @property
    def preview_concat(self) -> Path:
        return self.preview_dir / "concat.txt"

    def scene_visuals_dir(self, scene_id: str) -> Path:
        return self.visuals_dir / scene_id

    def scene_image_path(self, scene_id: str, suffix: str = ".jpg") -> Path:
        return self.scene_visuals_dir(scene_id) / f"image{suffix}"

    def scene_image_meta(self, scene_id: str) -> Path:
        return self.scene_visuals_dir(scene_id) / "image.meta.json"

    def scene_image_review(self, scene_id: str) -> Path:
        return self.scene_visuals_dir(scene_id) / IMAGE_REVIEW_FILENAME

    def visual_bible_json(self) -> Path:
        return self.stages_dir / VISUAL_BIBLE_FILENAME

    def image_batch_manifest(self) -> Path:
        return self.visuals_dir / IMAGE_BATCH_MANIFEST_FILENAME

    @property
    def graphics_dir(self) -> Path:
        return self.artifacts_dir / "graphics"

    def scene_graphics_dir(self, scene_id: str) -> Path:
        return self.graphics_dir / scene_id

    def scene_graphic_png(self, scene_id: str) -> Path:
        return self.scene_graphics_dir(scene_id) / "graphic.png"

    def scene_graphic_meta(self, scene_id: str) -> Path:
        return self.scene_graphics_dir(scene_id) / "graphic.meta.json"

    def scene_map_base(self, scene_id: str) -> Path:
        return self.scene_graphics_dir(scene_id) / "map_base.png"

    def scene_map_bg(self, scene_id: str) -> Path:
        return self.scene_graphics_dir(scene_id) / "map_bg.png"

    def scene_map_route(self, scene_id: str) -> Path:
        return self.scene_graphics_dir(scene_id) / "map_route.png"

    def scene_map_mask(self, scene_id: str) -> Path:
        return self.scene_graphics_dir(scene_id) / "map_mask.png"

    def scene_map_ring(self, scene_id: str) -> Path:
        return self.scene_graphics_dir(scene_id) / "map_ring.png"

    def scene_map_meta(self, scene_id: str) -> Path:
        return self.scene_graphics_dir(scene_id) / "map.meta.json"

    @property
    def graphics_contact_sheet(self) -> Path:
        return self.graphics_dir / GRAPHICS_CONTACT_SHEET_FILENAME

    def scene_image_history_dir(self, scene_id: str) -> Path:
        return self.scene_visuals_dir(scene_id) / "history"

    def contact_sheet(self) -> Path:
        return self.visuals_dir / CONTACT_SHEET_FILENAME

    def contact_sheet_repairs(self) -> Path:
        return self.visuals_dir / CONTACT_SHEET_REPAIRS_FILENAME

    def iter_layout_dirs(self) -> tuple[Path, ...]:
        return (
            self.stages_dir,
            self.audio_dir,
            self.visuals_dir,
            self.graphics_dir,
            self.subtitles_dir,
            self.render_dir,
            self.logs_dir,
            self.preview_dir,
            self.preview_segments_dir,
        )


def project_paths(project_id: str, *, projects_root: Path | None = None) -> ProjectPaths:
    safe_id = validate_project_id(project_id)
    base = (projects_root or default_projects_root()).resolve()
    root = (base / safe_id).resolve()
    if not root.is_relative_to(base):
        raise UnsafeProjectIdError(f"Project id {project_id!r} escapes the projects root")
    if root == base:
        raise UnsafeProjectIdError(f"Project id {project_id!r} is not a project subdirectory")
    return ProjectPaths(root=root)


def ensure_project_layout(paths: ProjectPaths) -> None:
    for directory in paths.iter_layout_dirs():
        directory.mkdir(parents=True, exist_ok=True)
