from __future__ import annotations

import hashlib
import json
from typing import Any

from docprod.product.errors import IdempotencyConflictError
from docprod.product.models import IdempotencyRecord
from docprod.product.services import ProductService


def hash_payload(payload: Any) -> str:
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def remember(
    service: ProductService,
    *,
    user_id: str,
    action: str,
    key: str | None,
    payload: Any,
    status_code: int,
    body: dict[str, Any],
    result_type: str | None = None,
    result_id: str | None = None,
) -> None:
    if not key:
        return
    record = IdempotencyRecord(
        key=key,
        user_id=user_id,
        action=action,
        request_hash=hash_payload(payload),
        status_code=status_code,
        body=body,
        result_type=result_type,
        result_id=result_id,
        created_at=service.clock(),
    )
    service.repo.put_idempotency(record)


def lookup(
    service: ProductService,
    *,
    user_id: str,
    action: str,
    key: str | None,
    payload: Any,
) -> IdempotencyRecord | None:
    if not key:
        return None
    record = service.repo.idempotency_lookup(user_id, action, key)
    if record is None:
        return None
    if record.request_hash != hash_payload(payload):
        raise IdempotencyConflictError("idempotency key reused with different payload")
    return record
