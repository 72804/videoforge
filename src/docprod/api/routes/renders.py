from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import Response

from docprod.api.dependencies import current_user, get_ctx, get_service, run_queued_job
from docprod.api.errors import map_product_error
from docprod.api.idempotency import lookup, remember
from docprod.api.schemas import GenerateRequest, JobAccepted
from docprod.product.errors import NotFoundError, OwnershipError, ProductError
from docprod.product.models import TelegramUser
from docprod.product.services import ProductService

router = APIRouter(tags=["renders"])


@router.post(
    "/projects/{project_id}/render",
    status_code=202,
    response_model=JobAccepted,
    operation_id="renderProject",
)
def render_project(
    project_id: str,
    body: GenerateRequest,
    request: Request,
    user: TelegramUser = Depends(current_user),
    service: ProductService = Depends(get_service),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> JobAccepted:
    payload = body.model_dump()
    try:
        hit = lookup(
            service, user_id=user.id, action="render", key=idempotency_key, payload=payload
        )
        if hit:
            return JobAccepted.model_validate(hit.body)
        job = service.queue_generation(
            user.id, project_id, body.quote_id, kind="render"
        )
        job = run_queued_job(get_ctx(request), job)
    except ProductError as exc:
        raise map_product_error(exc) from exc
    accepted = JobAccepted(job_id=job.id, status=job.status.value)
    remember(
        service,
        user_id=user.id,
        action="render",
        key=idempotency_key,
        payload=payload,
        status_code=202,
        body=accepted.model_dump(),
    )
    return accepted


@router.get("/media/{asset_version_id}", operation_id="getMedia")
def get_media(
    asset_version_id: str,
    user: TelegramUser = Depends(current_user),
    service: ProductService = Depends(get_service),
) -> Response:
    version = service.repo.asset_versions.get(asset_version_id)
    if version is None:
        raise map_product_error(NotFoundError("asset not found"))
    asset = service.repo.assets[version.asset_id]
    project = service.repo.projects.get(asset.project_id)
    if project is None or project.user_id != user.id:
        raise map_product_error(OwnershipError("forbidden"))
    try:
        data = service.storage.get_bytes(version.storage_key)
    except (FileNotFoundError, KeyError) as exc:
        raise map_product_error(NotFoundError("asset bytes missing")) from exc
    return Response(content=data, media_type="application/octet-stream")
