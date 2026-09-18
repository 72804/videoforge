from __future__ import annotations

import pytest

from docprod.config import Settings, get_settings, require_paid_apis_enabled
from docprod.exceptions import PaidApiDisabledError
from docprod.logging_utils import InvalidLogLevelError, configure_logging


def test_paid_apis_default_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALLOW_PAID_APIS", raising=False)
    settings = Settings(_env_file=None)
    assert settings.allow_paid_apis is False
    assert settings.openai_key_configured() is False


def test_paid_provider_gate_rejects(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALLOW_PAID_APIS", "false")
    get_settings.cache_clear()
    try:
        with pytest.raises(PaidApiDisabledError, match="mock-openai"):
            require_paid_apis_enabled("mock-openai")
    finally:
        get_settings.cache_clear()


def test_paid_provider_gate_allows_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALLOW_PAID_APIS", "true")
    get_settings.cache_clear()
    try:
        require_paid_apis_enabled("mock-openai")
    finally:
        get_settings.cache_clear()


def test_configure_logging_and_reject_invalid_level() -> None:
    logger = configure_logging(Settings(log_level="DEBUG", _env_file=None))
    assert logger.level == 10
    handlers = len(logger.handlers)
    configure_logging(Settings(log_level="INFO"))
    assert len(logger.handlers) == handlers
    with pytest.raises(InvalidLogLevelError):
        configure_logging(Settings(log_level="VERBOSE"))
