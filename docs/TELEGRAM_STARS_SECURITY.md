# Telegram Stars security (Phase 15)

Invoice API used: Bot HTTP `createInvoiceLink` with `currency=XTR`, `provider_token=""`, `prices[].amount` = integer Stars (not cents, not USD). Mini App opens the returned URL with `WebApp.openInvoice`. Telegram then sends `pre_checkout_query` (answer within ~10s) and `message.successful_payment`.

Refund API wrapped: `refundStarPayment` (`user_id` + `telegram_payment_charge_id`). Not called automatically on generation failure.

## Threats and defenses

| Threat | Defense |
| --- | --- |
| Client changes Stars amount | Invoice amount taken only from stored `StarQuote.stars`. Endpoint has no client price field. Pre-checkout compares Telegram `total_amount` to quote. |
| Replay old invoice | Quote TTL; expired quotes rejected at invoice, pre-checkout, and success. Plan hash must still match. |
| Another user's quote | Auth session + ownership check. Pre-checkout `from.id` must map to the same `TelegramUser` as the intent. |
| Frontend claims paid | Ignored. Generation requires `TelegramPayment` + authorized quote from webhook/success path. |
| Duplicate `successful_payment` | Unique `telegram_payment_id`; early return if already stored. One `StarTransaction` `PURCHASE`. |
| Forged webhook | Production requires secret header; mismatch → 401. |
| Pre-checkout amount/currency mismatch | Reject with `ok=false`. |
| Stale plan | Quote `generation_plan_hash` vs live plan / intent `plan_hash`. |
| Payment succeeded, Mini App callback lost | `GET .../payment-status` and `GET .../latest-quote` restore `PAID`. |
| Payload leakage | Telegram payload is `PaymentIntent.id` only. |

## Refund foundation

`TelegramPayment.refund_status` may be `""`, `REFUND_PENDING`, `REFUNDED`, `REFUND_FAILED`. Future policy should refund only after an explicit operator decision, never on every mock/provider failure.
