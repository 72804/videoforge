from fastapi.testclient import TestClient

from docprod.api.app import create_app
from docprod.product.services import ProductService


def test_production_cors_allows_exact_origin_only() -> None:
    app = create_app(
        service=ProductService(bot_token="test-bot-token"),
        env="production",
        cors_origins=["https://studio.example"],
        payment_mode="fake",
        webhook_secret="hook-secret",
        generation_mode="mock",
        allow_paid_generation=False,
    )
    client = TestClient(app)
    allowed = client.get("/health", headers={"Origin": "https://studio.example"})
    assert allowed.headers.get("access-control-allow-origin") == "https://studio.example"
    denied = client.get("/health", headers={"Origin": "https://evil.example"})
    assert denied.headers.get("access-control-allow-origin") != "https://evil.example"


def test_production_webhook_still_requires_secret() -> None:
    app = create_app(
        env="production",
        webhook_secret="hook-secret",
        payment_mode="fake",
        cors_origins=["https://studio.example"],
    )
    client = TestClient(app)
    assert client.post("/telegram/webhook", json={"message": {"text": "/start"}}).status_code == 401
    ok = client.post(
        "/telegram/webhook",
        json={"weird": True},
        headers={"X-Telegram-Bot-Api-Secret-Token": "hook-secret"},
    )
    assert ok.status_code == 200
    assert ok.json() == {"ok": True}
