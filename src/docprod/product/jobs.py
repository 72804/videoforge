from __future__ import annotations

from docprod.product.enums import JobStatus
from docprod.product.errors import JobStateError

ALLOWED: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.WAITING_FOR_PAYMENT: frozenset(
        {JobStatus.QUEUED, JobStatus.CANCELLED, JobStatus.FAILED}
    ),
    JobStatus.QUEUED: frozenset(
        {JobStatus.PLANNING, JobStatus.RECOVERING_REMOTE, JobStatus.CANCELLED, JobStatus.FAILED}
    ),
    JobStatus.PLANNING: frozenset(
        {
            JobStatus.GENERATING_SCRIPT,
            JobStatus.RECOVERING_REMOTE,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        }
    ),
    JobStatus.GENERATING_SCRIPT: frozenset(
        {
            JobStatus.GENERATING_IMAGES,
            JobStatus.RECOVERING_REMOTE,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        }
    ),
    JobStatus.GENERATING_IMAGES: frozenset(
        {
            JobStatus.GENERATING_VIDEO,
            JobStatus.GENERATING_AUDIO,
            JobStatus.RECOVERING_REMOTE,
            JobStatus.PARTIAL,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        }
    ),
    JobStatus.GENERATING_VIDEO: frozenset(
        {
            JobStatus.GENERATING_AUDIO,
            JobStatus.RECOVERING_REMOTE,
            JobStatus.PARTIAL,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        }
    ),
    JobStatus.GENERATING_AUDIO: frozenset(
        {
            JobStatus.RENDERING,
            JobStatus.RECOVERING_REMOTE,
            JobStatus.PARTIAL,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        }
    ),
    JobStatus.RENDERING: frozenset(
        {JobStatus.COMPLETED, JobStatus.PARTIAL, JobStatus.FAILED, JobStatus.CANCELLED}
    ),
    JobStatus.RECOVERING_REMOTE: frozenset(
        {
            JobStatus.PLANNING,
            JobStatus.GENERATING_SCRIPT,
            JobStatus.GENERATING_IMAGES,
            JobStatus.GENERATING_VIDEO,
            JobStatus.GENERATING_AUDIO,
            JobStatus.RENDERING,
            JobStatus.COMPLETED,
            JobStatus.PARTIAL,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        }
    ),
    JobStatus.PARTIAL: frozenset({JobStatus.QUEUED, JobStatus.CANCELLED}),
    JobStatus.FAILED: frozenset({JobStatus.QUEUED, JobStatus.CANCELLED}),
    JobStatus.COMPLETED: frozenset(),
    JobStatus.CANCELLED: frozenset(),
}


def can_transition(current: JobStatus, nxt: JobStatus) -> bool:
    return nxt in ALLOWED.get(current, frozenset())


def transition(current: JobStatus, nxt: JobStatus) -> JobStatus:
    if not can_transition(current, nxt):
        raise JobStateError(f"cannot move from {current} to {nxt}")
    return nxt
