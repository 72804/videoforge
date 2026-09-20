from __future__ import annotations

from fastapi import APIRouter, Depends

from docprod.api.dependencies import current_user, get_service
from docprod.api.errors import map_product_error
from docprod.api.schemas import ProjectCreate, ProjectPatch, ProjectSummaryView
from docprod.product.enums import AspectRatio, DurationMode, ProjectStatus
from docprod.product.errors import ProductError
from docprod.product.models import Project, TelegramUser
from docprod.product.services import ProductService

router = APIRouter(tags=["projects"])


def _summary(
    service: ProductService, project: Project, *, detail: bool = False
) -> ProjectSummaryView:
    versions = service.repo.active_versions(project.id)
    duration = sum(v.duration_seconds for v in versions) or None
    jobs = [j for j in service.repo.jobs.values() if j.project_id == project.id]
    progress = None
    active_job_id = None
    active_job_status = None
    if jobs:
        latest = max(jobs, key=lambda j: j.created_at)
        progress = {key: int(val["completed"]) for key, val in latest.progress.items()}
        active_job_id = latest.id
        active_job_status = latest.status.value
    payload: dict = {
        "id": project.id,
        "title": project.title,
        "status": project.status.value,
        "duration_seconds": duration,
        "scene_count": len(service.repo.scenes_for(project.id)),
        "progress": progress,
        "updated_at": project.updated_at.isoformat(),
        "active_job_id": active_job_id,
        "active_job_status": active_job_status,
    }
    if detail:
        payload.update(
            prompt=project.prompt,
            duration_mode=project.duration_mode.value,
            target_duration_seconds=project.target_duration_seconds,
            aspect_ratio=project.aspect_ratio.value,
            language=project.language,
            quality_profile=project.quality_profile,
            default_image_model=project.default_image_model,
            default_video_model=project.default_video_model,
            default_text_model=project.default_text_model,
            default_voice_model=project.default_voice_model,
            style=project.style,
        )
    return ProjectSummaryView(**payload)


@router.post("/projects", response_model=ProjectSummaryView, operation_id="createProject")
def create_project(
    body: ProjectCreate,
    user: TelegramUser = Depends(current_user),
    service: ProductService = Depends(get_service),
) -> ProjectSummaryView:
    try:
        project = service.create_project(
            user.id,
            title=(body.title or "Untitled").strip() or "Untitled",
            prompt=body.prompt,
            duration_mode=DurationMode(body.duration_mode),
            target_duration_seconds=body.target_duration_seconds,
            aspect_ratio=AspectRatio(body.aspect_ratio),
            language=body.language,
            quality_profile=body.quality_profile,
            default_image_model=body.default_image_model,
            default_video_model=body.default_video_model,
            default_text_model=body.default_text_model,
            default_voice_model=body.default_voice_model,
            style=body.style,
        )
    except ProductError as exc:
        raise map_product_error(exc) from exc
    return _summary(service, project, detail=True)


@router.get("/projects", response_model=list[ProjectSummaryView], operation_id="listProjects")
def list_projects(
    user: TelegramUser = Depends(current_user),
    service: ProductService = Depends(get_service),
) -> list[ProjectSummaryView]:
    rows = [
        p
        for p in service.repo.projects_for(user.id)
        if p.status is not ProjectStatus.ARCHIVED
    ]
    return [_summary(service, p) for p in sorted(rows, key=lambda p: p.updated_at, reverse=True)]


@router.get(
    "/projects/{project_id}",
    response_model=ProjectSummaryView,
    operation_id="getProject",
)
def get_project(
    project_id: str,
    user: TelegramUser = Depends(current_user),
    service: ProductService = Depends(get_service),
) -> ProjectSummaryView:
    try:
        project = service._require_project(user.id, project_id)
    except ProductError as exc:
        raise map_product_error(exc) from exc
    return _summary(service, project, detail=True)


@router.patch(
    "/projects/{project_id}",
    response_model=ProjectSummaryView,
    operation_id="patchProject",
)
def patch_project(
    project_id: str,
    body: ProjectPatch,
    user: TelegramUser = Depends(current_user),
    service: ProductService = Depends(get_service),
) -> ProjectSummaryView:
    fields = body.model_dump(exclude_none=True)
    if "duration_mode" in fields:
        fields["duration_mode"] = DurationMode(fields["duration_mode"])
    if "aspect_ratio" in fields:
        fields["aspect_ratio"] = AspectRatio(fields["aspect_ratio"])
    try:
        project = service.update_project(user.id, project_id, **fields)
    except ProductError as exc:
        raise map_product_error(exc) from exc
    return _summary(service, project, detail=True)


@router.delete(
    "/projects/{project_id}",
    response_model=ProjectSummaryView,
    operation_id="archiveProject",
)
def archive_project(
    project_id: str,
    user: TelegramUser = Depends(current_user),
    service: ProductService = Depends(get_service),
) -> ProjectSummaryView:
    try:
        project = service.archive_project(user.id, project_id)
    except ProductError as exc:
        raise map_product_error(exc) from exc
    return _summary(service, project)
