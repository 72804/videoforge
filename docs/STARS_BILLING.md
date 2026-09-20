# Telegram Stars billing (Phase 13A)

Provider cost and customer Stars are separate ledgers.

```
GenerationPlan (hash)
   → ProviderCostEstimate (USD, server catalog)
   → PricingPolicy.stars_for_usd (configurable markup)
   → StarQuote (stars, plan_hash, expires_at)
```

Never compute a customer price from Mini App fields alone.
Never treat client `payment_success=true` as authorization.

`PricingPolicy.stars_per_provider_usd` is **our** configuration. This document
does not claim an official Telegram USD↔Stars FX rate.

## MVP mechanism: A — pay per generation

One Telegram invoice per `StarQuote`:

> Generate this project — {N} ⭐

Payment payload stores `quote_id` + `plan_hash`. A confirmed
`telegram_payment_id` authorizes **that plan** once (idempotent).

Why this is the MVP default:

- Maps 1:1 onto a hashed plan
- No internal credit wallet to reconcile
- Quote expiry is obvious (invoice/quote TTL)
- Refunds attach to a single job

## Alternative: B — prepaid credits

User buys a Stars pack → `StarTransaction.PURCHASE` → internal balance →
`GENERATION_DEBIT` per job.

Useful later for small regenerations (one scene) without a new invoice
each tap. Requires balance integrity, partial refunds, and Mini App wallet
UX. Not required to ship 13F if invoices cover full-project generate.

## Telegram policy

Invoice, pre-checkout, and `successful_payment` field details are
implemented in Phase 13F against current Bot API docs. This phase does
not invent those rules.

## Empty provider result

If Veo (or similar) returns no video but bills the provider:

- `provider_outcome = EMPTY_RESULT`
- `provider_billed = BILLED`
- `customer_billing = POLICY_PENDING`

Do not auto-refund, auto-retry, or auto-charge the customer in code until
product policy is chosen in 13F.
