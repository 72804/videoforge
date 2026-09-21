from __future__ import annotations

from typing import Any

from docprod.product.enums import AttemptStatus, PlanItemType
from docprod.product.models import GenerationAttempt, GenerationJob
from docprod.product.plans import canonical_json, sha256_text
from docprod.product.repository import MemoryRepository
from docprod.product.services import ProductService


def request_fingerprint(
    *,
    provider: str,
    model: str,
    item_type: PlanItemType,
    scene_id: str | None,
    extra: dict[str, Any] | None = None,
) -> str:
    payload = {
        "provider": provider,
        "model": model,
        "item_type": item_type.value,
        "scene_id": scene_id,
        "extra": extra or {},
    }
    return sha256_text(canonical_json(payload))


def existing_paid_attempt(
    repo: MemoryRepository, job_id: str, fingerprint: str
) -> GenerationAttempt | None:
    matches = [
        attempt for attempt in repo.attempts_for_job(job_id) if attempt.request_hash == fingerprint
    ]
    if not matches:
        return None
    return max(matches, key=lambda row: row.created_at)


def must_not_resubmit(attempt: GenerationAttempt) -> bool:
    if attempt.status is AttemptStatus.SUCCEEDED:
        return True
    if attempt.status in {
        AttemptStatus.SUBMITTED,
        AttemptStatus.RECOVERING_REMOTE,
    }:
        return True
    if attempt.status is AttemptStatus.FAILED and attempt.remote_operation_id:
        return True
    return False


def accounted_usd(job: GenerationJob, repo: MemoryRepository) -> float:
    """Known actuals plus reserved/estimated in-flight and completed-without-usage."""
    total = 0.0
    for attempt in repo.attempts_for_job(job.id):
        if attempt.status is AttemptStatus.FAILED_UNBILLED:
            continue
        if attempt.status is AttemptStatus.FAILED and not attempt.remote_operation_id:
            continue
        if attempt.actual_provider_cost is not None:
            total += attempt.actual_provider_cost
        else:
            total += attempt.estimated_provider_cost
    return round(total, 6)


def assert_within_cap(job: GenerationJob, additional_usd: float, *, spent: float) -> None:
    projected = spent + additional_usd
    if projected - 1e-9 > job.provider_cost_cap:
        raise CostCapExceeded(f"projected {projected} exceeds cap {job.provider_cost_cap}")


class CostCapExceeded(RuntimeError):
    pass


def recover_submitted_without_resubmit(
    service: ProductService, job_id: str
) -> list[GenerationAttempt]:
    """Mark in-flight remotes as recovering. Never submits a second paid request."""
    recovered: list[GenerationAttempt] = []
    for attempt in service.repo.attempts_for_job(job_id):
        if not attempt.remote_operation_id:
            continue
        if attempt.status not in {AttemptStatus.SUBMITTED, AttemptStatus.RECOVERING_REMOTE}:
            continue
        attempt.status = AttemptStatus.RECOVERING_REMOTE
        attempt.updated_at = service.clock()
        recovered.append(attempt)
    return recovered
