from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qsl, unquote

from pydantic import BaseModel, ConfigDict

from docprod.product.errors import AuthError
from docprod.product.limits import DEFAULT_LIMITS, ProductLimits


class TelegramInitUser(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    username: str | None = None
    first_name: str | None = None
    language_code: str | None = None


class TelegramInitData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user: TelegramInitUser
    auth_date: int
    query_id: str | None = None
    raw: dict[str, str]


def webapp_secret_key(bot_token: str) -> bytes:
    return hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()


def data_check_string(fields: dict[str, str]) -> str:
    pairs = [f"{key}={value}" for key, value in sorted(fields.items()) if key != "hash"]
    return "\n".join(pairs)


def sign_init_data(fields: dict[str, str], bot_token: str) -> str:
    digest = hmac.new(
        webapp_secret_key(bot_token),
        data_check_string(fields).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return digest


def parse_init_data(init_data: str) -> dict[str, str]:
    if not init_data.strip():
        raise AuthError("empty initData")
    pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=False)
    return {unquote(key): unquote(value) for key, value in pairs}


def validate_init_data(
    init_data: str,
    *,
    bot_token: str,
    now: datetime | None = None,
    limits: ProductLimits | None = None,
) -> TelegramInitData:
    """Validate Telegram Mini App initData. Never trust client-supplied user ids."""
    if not bot_token.strip():
        raise AuthError("bot token is not configured")
    fields = parse_init_data(init_data)
    received = fields.get("hash", "")
    if not received:
        raise AuthError("missing hash")
    expected = sign_init_data(fields, bot_token)
    if not hmac.compare_digest(received, expected):
        raise AuthError("invalid initData signature")
    raw_user = fields.get("user")
    if not raw_user:
        raise AuthError("missing user")
    try:
        user_payload: dict[str, Any] = json.loads(raw_user)
    except json.JSONDecodeError as exc:
        raise AuthError("malformed user") from exc
    try:
        auth_date = int(fields.get("auth_date") or "0")
    except ValueError as exc:
        raise AuthError("malformed auth_date") from exc
    current = now or datetime.now(UTC)
    age = int(current.timestamp()) - auth_date
    max_age = (limits or DEFAULT_LIMITS).init_data_max_age_seconds
    if age < 0 or age > max_age:
        raise AuthError("expired initData")
    user = TelegramInitUser.model_validate(user_payload)
    if user.id <= 0:
        raise AuthError("invalid telegram user id")
    return TelegramInitData(
        user=user,
        auth_date=auth_date,
        query_id=fields.get("query_id"),
        raw=fields,
    )


def build_init_data_query(
    *,
    bot_token: str,
    user: dict[str, Any],
    auth_date: int,
    query_id: str | None = None,
) -> str:
    """Test helper: produce a correctly signed initData query string."""
    fields = {"auth_date": str(auth_date), "user": json.dumps(user, separators=(",", ":"))}
    if query_id:
        fields["query_id"] = query_id
    fields["hash"] = sign_init_data(fields, bot_token)
    return "&".join(f"{key}={value}" for key, value in fields.items())
