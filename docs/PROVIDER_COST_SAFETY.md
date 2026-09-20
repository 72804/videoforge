# Provider cost safety

## Frozen plan

When the customer pays, the worker executes the frozen `GenerationPlan` snapshot in `job.progress["frozen_plan"]`: provider, model, quantity, seconds/images/chars, estimated USD, hard max USD. Safe equivalent substitution is not enabled for the first canary.

## Hard USD cap

`GenerationJob.provider_cost_cap` is set from `ProductLimits.max_provider_usd_per_job` (canary default **$2.00** when `REAL_GENERATION_CANARY=true`). Before every accounted paid step:

```text
spent(attempts) + next_estimate > cap  → STOP
```

No “hope it will be okay.”

## Paid operation idempotency

Each paid step stores a `request_hash` fingerprint plus optional `remote_operation_id`. If the worker dies after submit:

1. Reload attempts.
2. If `SUBMITTED` / `RECOVERING_REMOTE` with a remote id → poll/recover.
3. **Do not** POST a second paid request.

Provider success, provider billing, and customer Stars billing remain separate (`settlement.py`). Billed-empty → policy pending, not a blind retry.

## Retry classes (never a generic decorator on paid calls)

| Class | Action |
| --- | --- |
| Network before submit | bounded reconnect; no fingerprint yet |
| Provider polling | continue same remote id |
| Unbilled provider failure | bounded retry with **new** fingerprint only if policy allows |
| Uncertain billed state | recover only |
| Job retry | reclaim lease; reuse fingerprints |

## Failure categories (no automatic Stars refunds)

| Category | Customer message | Refund |
| --- | --- | --- |
| `CUSTOMER_FIX_REQUIRED` | update project | no |
| `RETRYABLE_INFRA` | delayed, we retry | no |
| `PROVIDER_UNBILLED_FAILURE` | can retry | no |
| `PROVIDER_BILLED_FAILURE` | support review | **manual** Telegram Stars refund only after ledger review |
| `INTERNAL_FAILURE` | support review | manual |

Do not auto-refund on first canary.

## Gates before any paid call

Project ownership, payment authorization, live plan hash, cost cap, concurrency/hourly limits, canary allowlist, moderation hook. The API is not an open provider proxy. Provider keys are absent from Vercel.

## First canary provider set (smallest complete path)

Script: OpenAI `gpt-5.6-luna`  
Stills: OpenAI `gpt-image-2.5-flare`  
Selective video: Google Veo 3.1 Lite (8s)  
Voice: OpenAI `gpt-4o-mini-tts`  
Music/SFX: local/procedural  
Render: FFmpeg  

Catalog prices in-repo (verify before live): Veo Lite **$0.05/s** → **$0.40** per 8s shot. Image list price is usage-based (estimated ~$0.05/still in the frozen plan). TTS is token-priced (~$0.03 budgeted). Script ~$0.02. **Do not treat these as invoices until the live dashboard is checked on enablement day.**
