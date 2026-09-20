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


def test_missing_user() -> None:
    from docprod.product.auth import sign_init_data

    fields = {"auth_date": str(AUTH_DATE)}
    fields["hash"] = sign_init_data(fields, BOT)
    query = "&".join(f"{key}={value}" for key, value in fields.items())
    with pytest.raises(AuthError, match="missing user"):
        validate_init_data(
            query,
            bot_token=BOT,
            now=datetime.fromtimestamp(AUTH_DATE + 10, tz=UTC),
        )


def test_same_telegram_id_updates_username() -> None:
    from docprod.product.services import ProductService

    now = int(datetime.now(UTC).timestamp())
    service = ProductService(bot_token=BOT)
    first = build_init_data_query(
        bot_token=BOT,
        user=USER,
        auth_date=now,
    )
    user = service.authenticate_telegram(first)
    later = build_init_data_query(
        bot_token=BOT,
        user={**USER, "username": "ada2"},
        auth_date=now,
    )
    again = service.authenticate_telegram(later)
    assert again.id == user.id
    assert again.username == "ada2"


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
