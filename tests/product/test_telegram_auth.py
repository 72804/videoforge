from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from docprod.product.auth import AuthError, build_init_data_query, validate_init_data
from docprod.product.limits import ProductLimits

BOT = "123456:TEST_TELEGRAM_BOT_TOKEN"
USER = {"id": 4242, "first_name": "Ada", "username": "ada", "language_code": "en"}
AUTH_DATE = 1_700_000_000


def test_valid_signature_fixture() -> None:
    query = build_init_data_query(bot_token=BOT, user=USER, auth_date=AUTH_DATE)
    parsed = validate_init_data(
        query,
        bot_token=BOT,
        now=datetime.fromtimestamp(AUTH_DATE + 10, tz=UTC),
    )
    assert parsed.user.id == 4242
    assert parsed.user.username == "ada"


def test_invalid_signature() -> None:
    query = build_init_data_query(bot_token=BOT, user=USER, auth_date=AUTH_DATE)
    query = query.replace("hash=", "hash=deadbeef")
    with pytest.raises(AuthError, match="invalid initData signature"):
        validate_init_data(
            query,
            bot_token=BOT,
            now=datetime.fromtimestamp(AUTH_DATE + 10, tz=UTC),
        )


def test_tampered_user() -> None:
    query = build_init_data_query(bot_token=BOT, user=USER, auth_date=AUTH_DATE)
    query = query.replace("%22id%22:4242", "%22id%22:1") if "%22id%22" in query else query.replace(
        '"id":4242', '"id":9999'
    )
    with pytest.raises(AuthError):
        validate_init_data(
            query,
            bot_token=BOT,
            now=datetime.fromtimestamp(AUTH_DATE + 10, tz=UTC),
        )


def test_expired_auth_date() -> None:
    query = build_init_data_query(bot_token=BOT, user=USER, auth_date=AUTH_DATE)
    limits = ProductLimits(init_data_max_age_seconds=60)
    with pytest.raises(AuthError, match="expired"):
        validate_init_data(
            query,
            bot_token=BOT,
            now=datetime.fromtimestamp(AUTH_DATE, tz=UTC) + timedelta(hours=2),
            limits=limits,
        )
