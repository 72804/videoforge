from __future__ import annotations

from pydantic import SecretStr

from docprod.config import Settings
from docprod.providers.higgsfield import (
    higgsfield_request_result,
    is_bare_higgsfield_request_url,
    official_higgsfield_response_url,
)


def _settings() -> Settings:
    return Settings(
        higgsfield_api_key_id=SecretStr("idpart"),
        higgsfield_api_key_secret=SecretStr("secretpart"),
        _env_file=None,
    )


class _FakeResponse:
    def __init__(self, payload: dict[str, object], status_code: int = 200) -> None:
        self.status_code = status_code
        self.content = b"{}" if payload else b""
        self._payload = payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import httpx

            request = httpx.Request("GET", "https://api.higgsfield.ai/requests/x/status")
            raise httpx.HTTPStatusError(
                "error",
                request=request,
                response=httpx.Response(self.status_code, request=request),
            )

    def json(self) -> dict[str, object]:
        return self._payload


def test_bare_request_url_detection() -> None:
    assert is_bare_higgsfield_request_url("https://api.higgsfield.ai/requests/abc-1")
    assert is_bare_higgsfield_request_url("https://api.higgsfield.ai/requests/abc-1/")
    assert not is_bare_higgsfield_request_url(
        "https://api.higgsfield.ai/requests/abc-1/status"
    )
    assert official_higgsfield_response_url("abc-1").endswith("/requests/abc-1/status")


def test_result_never_gets_bare_requests_url(monkeypatch) -> None:
    captured: list[str] = []

    class FakeClient:
        def __init__(self, timeout: float | None = None) -> None:
            del timeout

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def get(self, url: str, headers: dict[str, str] | None = None):
            captured.append(url)
            assert headers is not None
            assert headers["Authorization"].startswith("Key ")
            return _FakeResponse({"status": "completed"})

    monkeypatch.setattr("httpx.Client", FakeClient)
    payload = higgsfield_request_result("abc-1", settings=_settings())
    assert payload["status"] == "completed"
    assert captured == ["https://api.higgsfield.ai/requests/abc-1/status"]
    assert "https://api.higgsfield.ai/requests/abc-1" not in captured


def test_result_follows_exact_response_url(monkeypatch) -> None:
    captured: list[str] = []

    class FakeClient:
        def __init__(self, timeout: float | None = None) -> None:
            del timeout

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def get(self, url: str, headers: dict[str, str] | None = None):
            captured.append(url)
            return _FakeResponse({"video": {"url": "https://cdn.example/out.mp4"}})

    monkeypatch.setattr("httpx.Client", FakeClient)
    exact = "https://api.higgsfield.ai/custom-result/abc-1"
    extra = higgsfield_request_result(
        "abc-1",
        settings=_settings(),
        payload={"status": "completed", "response_url": exact},
    )
    assert captured == [exact]
    assert extra["video"]["url"] == "https://cdn.example/out.mp4"


def test_result_skips_http_when_status_has_video(monkeypatch) -> None:
    def boom(*args, **kwargs):
        raise AssertionError("must not GET result when video.url is present")

    monkeypatch.setattr("httpx.Client", boom)
    extra = higgsfield_request_result(
        "abc-1",
        settings=_settings(),
        payload={
            "status": "completed",
            "video": {"url": "https://cdn.example/clip.mp4"},
        },
    )
    assert extra == {}
