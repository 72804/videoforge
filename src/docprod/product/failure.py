from __future__ import annotations

from enum import StrEnum


class FailureCategory(StrEnum):
    CUSTOMER_FIX_REQUIRED = "CUSTOMER_FIX_REQUIRED"
    RETRYABLE_INFRA = "RETRYABLE_INFRA"
    PROVIDER_UNBILLED_FAILURE = "PROVIDER_UNBILLED_FAILURE"
    PROVIDER_BILLED_FAILURE = "PROVIDER_BILLED_FAILURE"
    INTERNAL_FAILURE = "INTERNAL_FAILURE"


CUSTOMER_SAFE_STATUS = {
    FailureCategory.CUSTOMER_FIX_REQUIRED: "Please update the project and try again.",
    FailureCategory.RETRYABLE_INFRA: "Generation is delayed. We will retry automatically.",
    FailureCategory.PROVIDER_UNBILLED_FAILURE: "Generation failed before billing. You can retry.",
    FailureCategory.PROVIDER_BILLED_FAILURE: (
        "Generation failed after the provider accepted the request. Support will review."
    ),
    FailureCategory.INTERNAL_FAILURE: "Generation failed. Support will review.",
}
