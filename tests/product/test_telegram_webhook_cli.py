from __future__ import annotations

from typer.testing import CliRunner

from docprod.cli import app
from docprod.config import get_settings

runner = CliRunner()

WEBHOOK_URL = "https://videoforge-dusky.vercel.app/telegram/webhook"


class _StubTelegram:
    def __init__(self, token: str) -> None:
        assert token
        self.token = token

    def set_webhook(self, url: str, *, secret_token: str = "") -> bool:
        raise NotImplementedError

    def webhook_info(self) -> dict[str, object]:
        raise NotImplementedError


def _settings(monkeypatch, **env: str) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-bot-token")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_URL", WEBHOOK_URL)
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "test-webhook-secret")
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()


def test_telegram_webhook_set_true(monkeypatch) -> None:
    class Ok(_StubTelegram):
        def set_webhook(self, url: str, *, secret_token: str = "") -> bool:
            assert url == WEBHOOK_URL
            assert secret_token == "test-webhook-secret"
            return True

    _settings(monkeypatch)
    monkeypatch.setattr("docprod.telegram.client.HttpxTelegramClient", Ok)
    result = runner.invoke(app, ["telegram-webhook-set"])
    assert result.exit_code == 0, result.output
    assert WEBHOOK_URL in result.output
    assert "test-bot-token" not in result.output
    assert "test-webhook-secret" not in result.output


def test_telegram_webhook_set_false(monkeypatch) -> None:
    class Rejected(_StubTelegram):
        def set_webhook(self, url: str, *, secret_token: str = "") -> bool:
            return False

    _settings(monkeypatch)
    monkeypatch.setattr("docprod.telegram.client.HttpxTelegramClient", Rejected)
    result = runner.invoke(app, ["telegram-webhook-set"])
    assert result.exit_code == 1
    assert "rejected" in result.output.lower()
    assert "test-bot-token" not in result.output
    assert "test-webhook-secret" not in result.output


def test_telegram_webhook_info(monkeypatch) -> None:
    class Info(_StubTelegram):
        def webhook_info(self) -> dict[str, object]:
            return {"url": WEBHOOK_URL, "pending_update_count": 2}

    _settings(monkeypatch)
    monkeypatch.setattr("docprod.telegram.client.HttpxTelegramClient", Info)
    result = runner.invoke(app, ["telegram-webhook-info"])
    assert result.exit_code == 0, result.output
    assert f"url={WEBHOOK_URL}" in result.output
    assert "pending=2" in result.output
    assert "test-bot-token" not in result.output
    assert "test-webhook-secret" not in result.output
