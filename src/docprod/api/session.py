from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timedelta

from docprod.product.errors import AuthError


class SessionIssuer:
    """HMAC session token: `{user_id}.{exp_unix}.{hex_sig}`.

    telegram_user_id is never the credential. Rotate `api_session_secret`
    independently of the Telegram bot token. Production should move to
    short-lived tokens plus refresh, or an opaque server-side session table.
    """

    def __init__(self, secret: str, *, ttl_seconds: int = 86400) -> None:
        if not secret.strip():
            raise ValueError("session secret required")
        self._secret = secret.encode("utf-8")
        self.ttl_seconds = ttl_seconds

    def issue(self, user_id: str, now: datetime) -> str:
        exp = int(now.timestamp()) + self.ttl_seconds
        payload = f"{user_id}.{exp}"
        sig = hmac.new(self._secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()
        return f"{payload}.{sig}"

    def parse(self, token: str, now: datetime) -> str:
        parts = token.split(".")
        if len(parts) != 3:
            raise AuthError("invalid session token")
        user_id, exp_raw, sig = parts
        payload = f"{user_id}.{exp_raw}"
        expected = hmac.new(self._secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            raise AuthError("invalid session token")
        try:
            exp = int(exp_raw)
        except ValueError as exc:
            raise AuthError("invalid session token") from exc
        if int(now.timestamp()) >= exp:
            raise AuthError("expired session token")
        return user_id


def later(now: datetime, seconds: int) -> datetime:
    return now + timedelta(seconds=seconds)
