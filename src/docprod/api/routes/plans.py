from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Request

from docprod.api.dependencies import current_user, get_ctx, get_service, run_queued_job
from docprod.api.errors import map_product_error
from docprod.api.idempotency import lookup, remember
from docprod.api.schemas import (
    GenerateRequest,
    JobAccepted,
    PlanLineItem,
    PlanRequest,
    PlanView,
    QuoteRequest,
    QuoteView,
)
from docprod.product.enums import PlanItemType
from docprod.product.errors import ProductError
from docprod.product.models import TelegramUser
from docprod.product.services import ProductService

router = APIRouter(tags=["planning"])


def plan_view(service: ProductService, project_id: str, plan) -> PlanView:
    counts = {item.type: item.quantity for item in plan.items}
    duration = sum(v.duration_seconds for v in service.repo.active_versions(project_id))
    return PlanView(
        plan_id=plan.id,
        plan_hash=plan.plan_hash,
        scene_count=len(service.repo.scenes_for(project_id)),
        duration_seconds=duration,
        image_generations=counts.get(PlanItemType.STILL, 0),
        video_generations=counts.get(PlanItemType.VIDEO, 0),
        tts=counts.get(PlanItemType.TTS, 0),
        music=counts.get(PlanItemType.MUSIC, 0),
        provider_cost_estimate=plan.estimated_provider_usd,
        customer_star_estimate=plan.customer_stars,
        line_items=[
            PlanLineItem(
                type=item.type.value,
                model=item.model,
                quantity=item.quantity,
                estimated_provider_usd=item.estimated_provider_usd,
                customer_stars=item.customer_stars,
            )
            for item in plan.items
        ],
    )


@router.post("/projects/{project_id}/plan", response_model=PlanView, operation_id="planProject")
def plan_project(
    project_id: str,
    body: PlanRequest,
    user: TelegramUser = Depends(current_user),
    service: ProductService = Depends(get_service),
) -> PlanView:
    try:
        plan = service.plan_project(
            user.id, project_id, kind=body.kind, scene_id=body.scene_id
        )
    except ProductError as exc:
        raise map_product_error(exc) from exc
    return plan_view(service, project_id, plan)


@router.post("/projects/{project_id}/quote", response_model=QuoteView, operation_id="quoteProject")
def quote_project(
    project_id: str,
    body: QuoteRequest,
    user: TelegramUser = Depends(current_user),
    service: ProductService = Depends(get_service),
) -> QuoteView:
    try:
        quote = service.quote_project(user.id, project_id, body.plan_id)
    except ProductError as exc:
        raise map_product_error(exc) from exc
    return QuoteView(
        quote_id=quote.id,
        plan_hash=quote.generation_plan_hash,
        stars=quote.stars,
        expires_at=quote.expires_at.isoformat(),
        status=quote.status.value,
    )


@router.get("/projects/{project_id}/latest-quote", operation_id="latestQuote")
def latest_quote(
    project_id: str,
    user: TelegramUser = Depends(current_user),
    service: ProductService = Depends(get_service),
) -> dict:
    from docprod.product.errors import NotFoundError
    from docprod.telegram.payments import customer_payment_status

    try:
        service._require_project(user.id, project_id)
        quotes = [q for q in service.repo.quotes.values() if q.project_id == project_id]
        if not quotes:
            raise NotFoundError("quote not found")
        quote = max(quotes, key=lambda q: q.created_at)
        plan = service.repo.plans[quote.generation_plan_id]
        status = customer_payment_status(service, user.id, quote.id)
    except ProductError as exc:
        raise map_product_error(exc) from exc
    return {
        "quote": QuoteView(
            quote_id=quote.id,
            plan_hash=quote.generation_plan_hash,
            stars=quote.stars,
            expires_at=quote.expires_at.isoformat(),
            status=quote.status.value,
        ).model_dump(),
        "plan": plan_view(service, project_id, plan).model_dump(),
        "payment_status": status,
    }


@router.post(
    "/projects/{project_id}/generate",
    response_model=JobAccepted,
    status_code=202,
    operation_id="generateProject",
)
def generate_project(
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
            service,
            user_id=user.id,
            action="generate",
            key=idempotency_key,
            payload=payload,
        )
        if hit:
            return JobAccepted.model_validate(hit.body)
        job = service.queue_generation(
            user.id,
            project_id,
            body.quote_id,
            kind=body.kind,
            scene_id=body.scene_id,
        )
        job = run_queued_job(get_ctx(request), job)
    except ProductError as exc:
        raise map_product_error(exc) from exc
    accepted = JobAccepted(job_id=job.id, status=job.status.value)
    remember(
        service,
        user_id=user.id,
        action="generate",
        key=idempotency_key,
        payload=payload,
        status_code=202,
        body=accepted.model_dump(),
        result_type="generation_job",
        result_id=job.id,
    )
    return accepted
