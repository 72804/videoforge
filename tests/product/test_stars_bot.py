from __future__ import annotations

from fastapi.testclient import TestClient

from docprod.api.app import create_app
from docprod.api.session import SessionIssuer
from docprod.product.auth import build_init_data_query
from docprod.product.services import ProductService
from docprod.product.worker import MockGenerationWorker
from docprod.telegram.bot import START_TEXT, handle_command
from docprod.telegram.client import FakeTelegramClient
from docprod.telegram.updates import dispatch_update

BOT = "stars-bot-token"


def _client(service: ProductService, telegram: FakeTelegramClient) -> TestClient:
    return TestClient(
        create_app(
            service=service,
            sessions=SessionIssuer("sess"),
            env="test",
            telegram=telegram,
            payment_mode="fake",
            webhook_secret="hook-secret",
        )
    )


def _auth(client: TestClient, tg_id: int = 88) -> str:
    from datetime import UTC, datetime

    query = build_init_data_query(
        bot_token=BOT,
        user={"id": tg_id, "first_name": "Pay"},
        auth_date=int(datetime.now(UTC).timestamp()),
    )
    return client.post("/api/v1/auth/telegram", json={"init_data": query}).json()["token"]


def _quote(client: TestClient, token: str) -> tuple[str, str, int]:
    headers = {"Authorization": f"Bearer {token}"}
    project = client.post(
        "/api/v1/projects",
        json={"prompt": "Two friends find a box on the table", "duration_mode": "AUTO"},
        headers=headers,
    ).json()
    plan = client.post(f"/api/v1/projects/{project['id']}/plan", json={}, headers=headers).json()
    quote = client.post(
        f"/api/v1/projects/{project['id']}/quote",
        json={"plan_id": plan["plan_id"]},
        headers=headers,
    ).json()
    return project["id"], quote["quote_id"], quote["stars"]


def test_invoice_uses_server_stars_and_xtr() -> None:
    service = ProductService(bot_token=BOT)
    telegram = FakeTelegramClient()
    client = _client(service, telegram)
    token = _auth(client)
    _project_id, quote_id, stars = _quote(client, token)
    invoice = client.post(
        f"/api/v1/quotes/{quote_id}/telegram-invoice",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert invoice.status_code == 200, invoice.text
    assert invoice.json()["stars"] == stars
    assert invoice.json()["currency"] == "XTR"
    assert telegram.invoices[0]["stars"] == stars
    assert telegram.invoices[0]["currency"] == "XTR"
    assert "prompt" not in telegram.invoices[0]["payload"]


def test_wrong_user_quote_rejected() -> None:
    service = ProductService(bot_token=BOT)
    telegram = FakeTelegramClient()
    client = _client(service, telegram)
    owner = _auth(client, 1)
    other = _auth(client, 2)
    _pid, quote_id, _stars = _quote(client, owner)
    denied = client.post(
        f"/api/v1/quotes/{quote_id}/telegram-invoice",
        headers={"Authorization": f"Bearer {other}"},
    )
    assert denied.status_code == 403


def test_successful_payment_authorizes_and_is_idempotent() -> None:
    service = ProductService(bot_token=BOT)
    telegram = FakeTelegramClient()
    client = _client(service, telegram)
    token = _auth(client, 88)
    project_id, quote_id, stars = _quote(client, token)
    invoice = client.post(
        f"/api/v1/quotes/{quote_id}/telegram-invoice",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert invoice.status_code == 200
    intent_id = telegram.invoices[0]["payload"]
    update = {
        "pre_checkout_query": {
            "id": "pc1",
            "from": {"id": 88},
            "currency": "XTR",
            "total_amount": stars,
            "invoice_payload": intent_id,
        }
    }
    assert client.post(
        "/telegram/webhook",
        json=update,
        headers={"X-Telegram-Bot-Api-Secret-Token": "hook-secret"},
    ).status_code == 200
    assert telegram.pre_checkouts[0]["ok"] is True
    paid = {
        "message": {
            "from": {"id": 88},
            "successful_payment": {
                "currency": "XTR",
                "total_amount": stars,
                "invoice_payload": intent_id,
                "telegram_payment_charge_id": "charge-1",
            },
        }
    }
    client.post(
        "/telegram/webhook",
        json=paid,
        headers={"X-Telegram-Bot-Api-Secret-Token": "hook-secret"},
    )
    client.post(
        "/telegram/webhook",
        json=paid,
        headers={"X-Telegram-Bot-Api-Secret-Token": "hook-secret"},
    )
    status = client.get(
        f"/api/v1/quotes/{quote_id}/payment-status",
        headers={"Authorization": f"Bearer {token}"},
    ).json()
    assert status["status"] == "PAID"
    gen = client.post(
        f"/api/v1/projects/{project_id}/generate",
        json={"quote_id": quote_id},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert gen.status_code == 202
    paid = [t for t in service.repo.transactions.values() if t.telegram_payment_id == "charge-1"]
    assert len([t for t in paid if t.type.value == "PURCHASE"]) == 1


def test_pre_checkout_rejects_wrong_amount_and_currency() -> None:
    service = ProductService(bot_token=BOT)
    telegram = FakeTelegramClient()
    client = _client(service, telegram)
    token = _auth(client, 5)
    _pid, quote_id, stars = _quote(client, token)
    client.post(
        f"/api/v1/quotes/{quote_id}/telegram-invoice",
        headers={"Authorization": f"Bearer {token}"},
    )
    payload = telegram.invoices[0]["payload"]
    dispatch_update(
        service,
        telegram,
        {
            "pre_checkout_query": {
                "id": "pc-bad",
                "from": {"id": 5},
                "currency": "USD",
                "total_amount": stars,
                "invoice_payload": payload,
            }
        },
    )
    assert telegram.pre_checkouts[-1]["ok"] is False
    dispatch_update(
        service,
        telegram,
        {
            "pre_checkout_query": {
                "id": "pc-amt",
                "from": {"id": 5},
                "currency": "XTR",
                "total_amount": stars + 9,
                "invoice_payload": payload,
            }
        },
    )
    assert telegram.pre_checkouts[-1]["ok"] is False


def test_webhook_secret_and_unknown_update() -> None:
    service = ProductService(bot_token=BOT)
    client = _client(service, FakeTelegramClient())
    bad = client.post("/telegram/webhook", json={"message": {"text": "hi"}}, headers={})
    assert bad.status_code == 401
    ok = client.post(
        "/telegram/webhook",
        json={"weird": True},
        headers={"X-Telegram-Bot-Api-Secret-Token": "hook-secret"},
    )
    assert ok.json() == {"ok": True}
    prod = TestClient(create_app(env="production", webhook_secret="", payment_mode="fake"))
    missing = prod.post("/telegram/webhook", json={})
    assert missing.status_code == 401


def test_start_command_and_outbox_notification() -> None:
    telegram = FakeTelegramClient()
    handle_command(telegram, chat_id=42, text="/start", mini_app_url="https://studio.example")
    assert START_TEXT in telegram.messages[0]["text"]
    assert telegram.messages[0]["reply_markup"]["inline_keyboard"][0][0]["web_app"]["url"] == (
        "https://studio.example"
    )
    from docprod.product.models import NotificationOutbox, TelegramUser
    from docprod.product.notifications import TelegramNotificationSender, drain_outbox
    from docprod.product.repository import MemoryRepository

    repo = MemoryRepository()
    user = TelegramUser(telegram_user_id=42, first_name="Pay")
    repo.put_user(user)
    note = NotificationOutbox(
        user_id=user.id,
        project_id="p1",
        kind="project_ready",
        payload={},
    )
    repo.outbox[note.id] = note
    sender = TelegramNotificationSender(telegram, mini_app_url="https://studio.example")
    assert drain_outbox(repo, sender) == 1
    assert "ready" in telegram.messages[-1]["text"].lower()
    assert "Open Project" in str(telegram.messages[-1]["reply_markup"])
    telegram.fail_send = True
    retry = NotificationOutbox(user_id=user.id, kind="generation_failed", payload={})
    repo.outbox[retry.id] = retry
    assert drain_outbox(repo, sender, max_attempts=1) == 0
    assert repo.outbox[retry.id].status.value == "FAILED"


def test_start_without_public_https_url_has_no_web_app_button() -> None:
    from docprod.telegram.bot import LOCAL_STUDIO_NOTE, studio_keyboard

    telegram = FakeTelegramClient()
    handle_command(telegram, chat_id=7, text="/start", mini_app_url="http://127.0.0.1:3000")
    assert START_TEXT in telegram.messages[0]["text"]
    assert LOCAL_STUDIO_NOTE in telegram.messages[0]["text"]
    assert telegram.messages[0]["reply_markup"] is None
    assert studio_keyboard("") is None
    assert studio_keyboard("https://localhost/studio") is None
    from docprod.product.models import NotificationOutbox, TelegramUser
    from docprod.product.notifications import TelegramNotificationSender, drain_outbox
    from docprod.product.repository import MemoryRepository

    repo = MemoryRepository()
    user = TelegramUser(telegram_user_id=42, first_name="Pay")
    repo.put_user(user)
    note = NotificationOutbox(
        user_id=user.id,
        project_id="p1",
        kind="project_ready",
        payload={},
    )
    repo.outbox[note.id] = note
    sender = TelegramNotificationSender(telegram, mini_app_url="https://studio.example")
    assert drain_outbox(repo, sender) == 1
    assert "ready" in telegram.messages[-1]["text"].lower()
    assert "Open Project" in str(telegram.messages[-1]["reply_markup"])
    telegram.fail_send = True
    retry = NotificationOutbox(user_id=user.id, kind="generation_failed", payload={})
    repo.outbox[retry.id] = retry
    assert drain_outbox(repo, sender, max_attempts=1) == 0
    assert repo.outbox[retry.id].status.value == "FAILED"


def test_paid_generation_guard() -> None:
    service = ProductService(bot_token=BOT)
    try:
        MockGenerationWorker(service, allow_paid_generation=True)
    except Exception as exc:
        assert "ALLOW_PAID_GENERATION" in str(exc)
    else:
        raise AssertionError("expected guard")


def test_simulated_invoice_hidden_when_not_telegram_mode() -> None:
    service = ProductService(bot_token=BOT)
    client = TestClient(create_app(service=service, env="test", payment_mode="simulated"))
    token = _auth(client, 9)
    _pid, quote_id, _stars = _quote(client, token)
    response = client.post(
        f"/api/v1/quotes/{quote_id}/telegram-invoice",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 404
