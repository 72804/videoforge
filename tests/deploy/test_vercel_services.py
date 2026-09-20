import json
from pathlib import Path


def _vercel() -> dict:
    return json.loads(Path("vercel.json").read_text(encoding="utf-8"))


def test_one_project_services_layout() -> None:
    cfg = _vercel()
    assert "framework" not in cfg
    assert set(cfg["services"]) == {"frontend", "backend"}
    frontend = cfg["services"]["frontend"]
    backend = cfg["services"]["backend"]
    assert frontend["root"] == "apps/telegram-mini-app"
    assert frontend["framework"] == "nextjs"
    assert backend["root"] == "services/api"
    assert backend["framework"] == "fastapi"
    assert backend["entrypoint"] == "app:app"


def test_public_rewrites_send_api_paths_to_backend() -> None:
    cfg = _vercel()
    sources = [rule["source"] for rule in cfg["rewrites"]]
    for needed in (
        "/health",
        "/ready",
        "/docs",
        "/telegram/webhook",
        "/internal/:path*",
        "/api/v1/:path*",
        "/(.*)",
    ):
        assert needed in sources
    by_source = {rule["source"]: rule["destination"]["service"] for rule in cfg["rewrites"]}
    assert by_source["/health"] == "backend"
    assert by_source["/ready"] == "backend"
    assert by_source["/telegram/webhook"] == "backend"
    assert by_source["/internal/:path*"] == "backend"
    assert by_source["/api/v1/:path*"] == "backend"
    assert by_source["/(.*)"] == "frontend"
    assert cfg["rewrites"][-1]["source"] == "/(.*)"
    assert cfg["rewrites"][-1]["destination"]["service"] == "frontend"


def test_frontend_catch_all_does_not_steal_backend_prefixes() -> None:
    cfg = _vercel()
    backend_sources = [
        rule["source"]
        for rule in cfg["rewrites"]
        if rule["destination"]["service"] == "backend"
    ]
    assert any(source.startswith("/api/v1") for source in backend_sources)
    assert "/create" not in backend_sources
    assert "/projects" not in backend_sources
    assert "/settings" not in backend_sources
