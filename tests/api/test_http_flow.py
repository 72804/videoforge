from __future__ import annotations

import io
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from PIL import Image

from docprod.api.app import create_app, export_openapi
from docprod.api.session import SessionIssuer
from docprod.product.auth import build_init_data_query
from docprod.product.limits import ProductLimits
from docprod.product.services import ProductService, freeze_clock

BOT = "test-bot-token"


def _now_ts() -> int:
    return int(datetime.now(UTC).timestamp())


def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (10, 20, 30)).save(buf, "JPEG")
    return buf.getvalue()


def _client(service: ProductService | None = None, env: str = "test") -> TestClient:
    svc = service or ProductService(bot_token=BOT)
    app = create_app(service=svc, env=env, sessions=SessionIssuer("sess"))
    return TestClient(app)


def _auth(client: TestClient, tg_id: int = 11, now: int | None = None) -> str:
    stamp = now if now is not None else _now_ts()
    query = build_init_data_query(
        bot_token=BOT,
        user={"id": tg_id, "first_name": "Ada"},
        auth_date=stamp,
    )
    response = client.post("/api/v1/auth/telegram", json={"init_data": query})
    assert response.status_code == 200, response.text
    return response.json()["token"]


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_health_and_models() -> None:
    client = _client()
    assert client.get("/health").json()["status"] == "ok"
    assert "password" not in client.get("/health").text.lower()
    models = client.get("/api/v1/models").json()
    assert models[0]["id"] == "auto"
    assert all("api_key" not in str(row).lower() for row in models)


def test_full_http_flow_and_security() -> None:
    service = ProductService(bot_token=BOT)
    client = _client(service)
    token = _auth(client, 11)
    other = _auth(client, 99)
    created = client.post(
        "/api/v1/projects",
        json={"prompt": "Two friends find a box", "duration_mode": "AUTO"},
        headers=_h(token),
    )
    assert created.status_code == 200
    project_id = created.json()["id"]
    detail = client.get(f"/api/v1/projects/{project_id}", headers=_h(token)).json()
    assert detail["prompt"] == "Two friends find a box"
    assert detail["duration_mode"] == "AUTO"
    assert client.get(f"/api/v1/projects/{project_id}", headers=_h(other)).status_code == 403
    a = client.post(
        f"/api/v1/projects/{project_id}/characters",
        json={"name": "Lea", "description": "curious"},
        headers=_h(token),
    ).json()
    b = client.post(
        f"/api/v1/projects/{project_id}/characters",
        json={"name": "Noah"},
        headers=_h(token),
    ).json()
    up = client.post(
        f"/api/v1/characters/{a['id']}/references",
        files={"file": ("x.jpg", _jpeg(), "image/jpeg")},
        data={"role": "front", "make_primary": "true"},
        headers=_h(token),
    )
    assert up.status_code == 200
    client.post(
        f"/api/v1/characters/{b['id']}/references",
        files={"file": ("../etc/passwd", _jpeg(), "image/jpeg")},
        headers=_h(token),
    )
    plan = client.post(
        f"/api/v1/projects/{project_id}/plan",
        json={},
        headers=_h(token),
    )
    assert plan.status_code == 200
    assert plan.json()["estimate_source"] == "server"
    quote = client.post(
        f"/api/v1/projects/{project_id}/quote",
        json={"plan_id": plan.json()["plan_id"]},
        headers=_h(token),
    )
    assert quote.status_code == 200
    quote_id = quote.json()["quote_id"]
    missing = client.post(
        f"/api/v1/projects/{project_id}/generate",
        json={"quote_id": quote_id},
        headers=_h(token),
    )
    assert missing.status_code == 402
    pay = client.post(
        f"/api/v1/dev/payments/{quote_id}/confirm",
        headers={**_h(token), "Idempotency-Key": "pay-1"},
    )
    assert pay.status_code == 200
    assert pay.json()["simulated"] is True
    pay2 = client.post(
        f"/api/v1/dev/payments/{quote_id}/confirm",
        headers={**_h(token), "Idempotency-Key": "pay-1"},
    )
    assert pay2.json()["quote_id"] == quote_id
    gen = client.post(
        f"/api/v1/projects/{project_id}/generate",
        json={"quote_id": quote_id},
        headers={**_h(token), "Idempotency-Key": "gen-1"},
    )
    assert gen.status_code == 202
    job_id = gen.json()["job_id"]
    gen2 = client.post(
        f"/api/v1/projects/{project_id}/generate",
        json={"quote_id": quote_id},
        headers={**_h(token), "Idempotency-Key": "gen-1"},
    )
    assert gen2.json()["job_id"] == job_id
    conflict = client.post(
        f"/api/v1/projects/{project_id}/generate",
        json={"quote_id": quote_id, "kind": "render"},
        headers={**_h(token), "Idempotency-Key": "gen-1"},
    )
    assert conflict.status_code == 409
    run = client.post(f"/api/v1/dev/jobs/{job_id}/run")
    assert run.status_code == 200
    job = client.get(f"/api/v1/jobs/{job_id}", headers=_h(token)).json()
    assert job["status"] == "COMPLETED"
    assert job["work_units"]
    scenes = client.get(f"/api/v1/projects/{project_id}/scenes", headers=_h(token)).json()
    assert len(scenes) >= 3
    image_id = scenes[0]["image_asset_version_id"]
    media = client.get(f"/api/v1/media/{image_id}", headers=_h(token))
    assert media.status_code == 200
    assert media.content == b"mock-still"
    assert client.get(f"/api/v1/media/{image_id}", headers=_h(other)).status_code == 403
    scene_id = scenes[0]["id"]
    edited = client.patch(
        f"/api/v1/scenes/{scene_id}",
        json={"motion_prompt": "slow pan only"},
        headers=_h(token),
    )
    assert edited.status_code == 200
    assert "video" in edited.json()["invalidated"]
    regen_plan = client.post(
        f"/api/v1/projects/{project_id}/plan",
        json={"kind": "scene_video", "scene_id": scene_id},
        headers=_h(token),
    )
    regen_quote = client.post(
        f"/api/v1/projects/{project_id}/quote",
        json={"plan_id": regen_plan.json()["plan_id"]},
        headers=_h(token),
    )
    assert regen_quote.status_code == 200, regen_quote.text
    client.post(
        f"/api/v1/dev/payments/{regen_quote.json()['quote_id']}/confirm",
        headers=_h(token),
    )
    regen = client.post(
        f"/api/v1/scenes/{scene_id}/regenerate-video",
        json={"quote_id": regen_quote.json()["quote_id"]},
        headers=_h(token),
    )
    assert regen.status_code == 202
    client.post(f"/api/v1/dev/jobs/{regen.json()['job_id']}/run")
    detail = client.get(f"/api/v1/scenes/{scene_id}", headers=_h(token)).json()
    assert len(detail["versions"]) >= 2
    versions = client.get(f"/api/v1/scenes/{scene_id}/versions", headers=_h(token)).json()[
        "versions"
    ]
    older = [v["id"] for v in versions if v["id"] != detail["active_version"]["id"]][0]
    client.post(f"/api/v1/scenes/{scene_id}/restore/{older}", headers=_h(token))
    client.post(f"/api/v1/scenes/{scene_id}/lock", headers=_h(token))
    locked = client.patch(
        f"/api/v1/scenes/{scene_id}",
        json={"visual_prompt": "nope"},
        headers=_h(token),
    )
    assert locked.status_code == 409
    client.post(f"/api/v1/scenes/{scene_id}/unlock", headers=_h(token))
    usage = client.get("/api/v1/usage", headers=_h(token)).json()
    assert usage["stars_purchased"] > 0
    assert any(row["simulated"] for row in usage["transactions"])


def test_auth_rejects_bad_init_data() -> None:
    client = _client()
    now = _now_ts()
    good = build_init_data_query(
        bot_token=BOT, user={"id": 5, "first_name": "A"}, auth_date=now
    )
    bad = good.replace("hash=", "hash=00")
    assert client.post("/api/v1/auth/telegram", json={"init_data": bad}).status_code == 401
    tampered = good.replace('"id":5', '"id":6')
    assert client.post("/api/v1/auth/telegram", json={"init_data": tampered}).status_code == 401
    expired = build_init_data_query(
        bot_token=BOT, user={"id": 5, "first_name": "A"}, auth_date=now - 100000
    )
    service = ProductService(
        bot_token=BOT,
        limits=ProductLimits(init_data_max_age_seconds=60),
        clock=freeze_clock(datetime.fromtimestamp(now, tz=UTC)),
    )
    client = _client(service)
    assert client.post("/api/v1/auth/telegram", json={"init_data": expired}).status_code == 401


def test_expired_quote_and_stale_plan() -> None:
    start = datetime(2026, 2, 1, tzinfo=UTC)
    service = ProductService(
        bot_token=BOT,
        limits=ProductLimits(quote_ttl_seconds=30),
        clock=freeze_clock(start),
    )
    client = _client(service)
    token = _auth(client, 21, now=int(start.timestamp()))
    project_id = client.post(
        "/api/v1/projects",
        json={"prompt": "hello world prompt", "duration_mode": "AUTO"},
        headers=_h(token),
    ).json()["id"]
    plan = client.post(
        f"/api/v1/projects/{project_id}/plan", json={}, headers=_h(token)
    ).json()
    quote = client.post(
        f"/api/v1/projects/{project_id}/quote",
        json={"plan_id": plan["plan_id"]},
        headers=_h(token),
    ).json()
    service.clock = freeze_clock(start + timedelta(minutes=5))
    expired = client.post(
        f"/api/v1/dev/payments/{quote['quote_id']}/confirm", headers=_h(token)
    )
    assert expired.status_code == 400
    service.clock = freeze_clock(start)
    client.post(
        f"/api/v1/projects/{project_id}/quote",
        json={"plan_id": plan["plan_id"]},
        headers=_h(token),
    )
    client.patch(
        f"/api/v1/projects/{project_id}",
        json={"prompt": "changed prompt text"},
        headers=_h(token),
    )
    stale = client.post(
        f"/api/v1/projects/{project_id}/quote",
        json={"plan_id": plan["plan_id"]},
        headers=_h(token),
    )
    assert stale.status_code == 409


def test_uploads_and_limits() -> None:
    service = ProductService(
        bot_token=BOT, limits=ProductLimits(max_upload_bytes=200, max_projects_per_user=1)
    )
    client = _client(service)
    token = _auth(client, 31)
    project_id = client.post(
        "/api/v1/projects",
        json={"prompt": "limit prompt here", "duration_mode": "AUTO"},
        headers=_h(token),
    ).json()["id"]
    second = client.post(
        "/api/v1/projects",
        json={"prompt": "another prompt here", "duration_mode": "AUTO"},
        headers=_h(token),
    )
    assert second.status_code == 400
    char = client.post(
        f"/api/v1/projects/{project_id}/characters",
        json={"name": "X"},
        headers=_h(token),
    ).json()
    huge = client.post(
        f"/api/v1/characters/{char['id']}/references",
        files={"file": ("a.jpg", b"x" * 500, "image/jpeg")},
        headers=_h(token),
    )
    assert huge.status_code == 400
    invalid = client.post(
        f"/api/v1/characters/{char['id']}/references",
        files={"file": ("a.jpg", b"not-an-image", "image/jpeg")},
        headers=_h(token),
    )
    assert invalid.status_code == 400
    cap = ProductService(bot_token=BOT, limits=ProductLimits(max_provider_usd_per_job=0.001))
    client2 = _client(cap)
    token2 = _auth(client2, 41)
    pid = client2.post(
        "/api/v1/projects",
        json={"prompt": "cap prompt text", "duration_mode": "AUTO"},
        headers=_h(token2),
    ).json()["id"]
    planned = client2.post(f"/api/v1/projects/{pid}/plan", json={}, headers=_h(token2))
    assert planned.status_code == 400


def test_dev_auth_and_hidden_in_production() -> None:
    client = _client(env="test")
    response = client.post("/api/v1/dev/auth", json={"telegram_user_id": 11, "first_name": "Dev"})
    assert response.status_code == 200
    assert response.json()["user"]["telegram_user_id"] == 11
    hidden = _client(env="production")
    assert hidden.post("/api/v1/dev/auth", json={"telegram_user_id": 11}).status_code == 404


def test_dev_payments_hidden_in_production() -> None:
    client = _client(env="production")
    token = _auth(client, 51)
    response = client.post("/api/v1/dev/payments/x/confirm", headers=_h(token))
    assert response.status_code == 404


def test_openapi_export(tmp_path) -> None:
    path = tmp_path / "openapi.json"
    payload = export_openapi(path)
    assert "/api/v1/auth/telegram" in payload["paths"]
    assert "/health" in payload["paths"]
    text = path.read_text(encoding="utf-8")
    assert "gemini_api_key" not in text
    assert "openai_api_key" not in text
