from __future__ import annotations

import pytest

from docprod.config import get_settings, require_paid_apis_enabled
from docprod.exceptions import PaidApiDisabledError


def test_paid_apis_default_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALLOW_PAID_APIS", raising=False)
    get_settings.cache_clear()
    try:
        assert get_settings().allow_paid_apis is False
    finally:
        get_settings.cache_clear()


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
