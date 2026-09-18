from __future__ import annotations

from docprod.exceptions import MaxPaidRequestsExceededError


class ModelRequestBudget:
    """Hard cap on live model Responses requests. Retries consume the same budget."""

    def __init__(self, max_requests: int) -> None:
        if max_requests < 0:
            raise ValueError("max_requests must be >= 0")
        self.max_requests = max_requests
        self.used_requests = 0
        self.stage_counts: dict[str, int] = {}

    @property
    def remaining_requests(self) -> int:
        return max(0, self.max_requests - self.used_requests)

    def reserve(self, stage: str, n: int = 1) -> None:
        if n < 1:
            raise ValueError("reserve count must be >= 1")
        if self.used_requests + n > self.max_requests:
            raise MaxPaidRequestsExceededError(
                f"Model request budget exhausted for stage {stage!r}: "
                f"used={self.used_requests} max={self.max_requests}. STOP."
            )
        self.used_requests += n
        self.stage_counts[stage] = self.stage_counts.get(stage, 0) + n
