from __future__ import annotations

from dataclasses import dataclass

from docprod.product.enums import CustomerBillingOutcome, ProviderBilledStatus, ProviderOutcome


@dataclass(frozen=True)
class AttemptSettlement:
    """Keep provider cost, provider outcome, and customer billing independent."""

    provider_outcome: ProviderOutcome
    provider_billed: ProviderBilledStatus
    customer_billing: CustomerBillingOutcome
    notes: str


def classify_attempt(
    *,
    outcome: ProviderOutcome,
    billed: ProviderBilledStatus,
) -> AttemptSettlement:
    """Represent refund eligibility. Do not silently refund or retry."""
    if outcome is ProviderOutcome.SUCCEEDED:
        customer = (
            CustomerBillingOutcome.DEBITED
            if billed is ProviderBilledStatus.BILLED
            else CustomerBillingOutcome.NOT_CHARGED
        )
        return AttemptSettlement(outcome, billed, customer, "success")
    if outcome is ProviderOutcome.EMPTY_RESULT and billed is ProviderBilledStatus.BILLED:
        return AttemptSettlement(
            outcome,
            billed,
            CustomerBillingOutcome.POLICY_PENDING,
            "provider billed empty result; product policy must decide credit/retry/charge",
        )
    if outcome is ProviderOutcome.FAILED and billed is ProviderBilledStatus.NOT_BILLED:
        return AttemptSettlement(
            outcome,
            billed,
            CustomerBillingOutcome.REFUND_ELIGIBLE,
            "failed before provider cost; eligible for refund/credit per policy",
        )
    if outcome is ProviderOutcome.FAILED and billed is ProviderBilledStatus.BILLED:
        return AttemptSettlement(
            outcome,
            billed,
            CustomerBillingOutcome.POLICY_PENDING,
            "provider billed a failed attempt; product policy must decide",
        )
    return AttemptSettlement(
        outcome, billed, CustomerBillingOutcome.NOT_CHARGED, "no customer debit"
    )
