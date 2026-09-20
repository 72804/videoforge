from __future__ import annotations

from fastapi import APIRouter, Depends

from docprod.api.dependencies import current_user, get_service
from docprod.api.errors import map_product_error
from docprod.api.schemas import JobView, WorkUnitView
from docprod.product.errors import ProductError
from docprod.product.models import TelegramUser
from docprod.product.services import ProductService

router = APIRouter(tags=["jobs"])


@router.get("/jobs/{job_id}", response_model=JobView, operation_id="getJob")
def get_job(
    job_id: str,
    user: TelegramUser = Depends(current_user),
    service: ProductService = Depends(get_service),
) -> JobView:
    try:
        view = service.get_job_status(user.id, job_id)
        job = service.repo.jobs[job_id]
    except ProductError as exc:
        raise map_product_error(exc) from exc
    units = [
        WorkUnitView(type=str(u["label"]), completed=int(u["completed"]), total=int(u["total"]))
        for u in view.units
    ]
    return JobView(
        job_id=job.id,
        project_id=job.project_id,
        status=job.status.value,
        work_units=units,
        current_stage=job.status.value,
        failure_message=job.failure_message,
        created_at=job.created_at.isoformat(),
        started_at=job.started_at.isoformat() if job.started_at else None,
        completed_at=job.completed_at.isoformat() if job.completed_at else None,
    )
