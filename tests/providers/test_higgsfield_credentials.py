from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr
from typer.testing import CliRunner

from docprod.cli import app
from docprod.config import Settings, get_settings, resolve_higgsfield_api_key
from docprod.product.higgsfield_scenes import (
    STORY_SPEC_RELATIVE,
    assert_higgsfield_live_authorized,
    build_higgsfield_scenes,
    load_existing_story,
)
from docprod.providers.higgsfield import (
    higgsfield_auth_header,
    higgsfield_credentials_present,
    submit_higgsfield_json,
)

_SECRET = "hf-secret-SHOULD-NOT-LEAK"


def _clear_hf_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "HF_API_KEY",
        "HIGGSFIELD_API_KEY",
        "HIGGSFIELD_API_KEY_ID",
        "HIGGSFIELD_API_KEY_SECRET",
    ):
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()


def _empty_settings() -> Settings:
    return Settings(_env_file=None)


def test_only_hf_api_key_resolves(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_hf_env(monkeypatch)
    monkeypatch.setenv("HF_API_KEY", "complete-key-no-colon")
    assert resolve_higgsfield_api_key(_empty_settings()) == "complete-key-no-colon"
    assert higgsfield_credentials_present(_empty_settings()) is True
    assert higgsfield_auth_header(_empty_settings()) == "Key complete-key-no-colon"


def test_only_legacy_split_resolves(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_hf_env(monkeypatch)
    monkeypatch.setenv("HIGGSFIELD_API_KEY_ID", "idpart")
    monkeypatch.setenv("HIGGSFIELD_API_KEY_SECRET", "secretpart")
    assert resolve_higgsfield_api_key(_empty_settings()) == "idpart:secretpart"
    assert higgsfield_credentials_present(_empty_settings()) is True
    assert higgsfield_auth_header(_empty_settings()) == "Key idpart:secretpart"


def test_neither_credential_is_false(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_hf_env(monkeypatch)
    assert resolve_higgsfield_api_key(_empty_settings()) is None
    assert higgsfield_credentials_present(_empty_settings()) is False


def test_hf_api_key_precedes_legacy_split(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_hf_env(monkeypatch)
    monkeypatch.setenv("HF_API_KEY", "complete-wins")
    monkeypatch.setenv("HIGGSFIELD_API_KEY_ID", "idpart")
    monkeypatch.setenv("HIGGSFIELD_API_KEY_SECRET", "secretpart")
    assert resolve_higgsfield_api_key(_empty_settings()) == "complete-wins"
    assert higgsfield_auth_header(_empty_settings()) == "Key complete-wins"


def test_live_auth_true_with_hf_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    if not Path(STORY_SPEC_RELATIVE).is_file():
        pytest.skip("checked-in story spec not available")
    from docprod.product.story_pipeline import inspect_locked_character_refs

    _clear_hf_env(monkeypatch)
    monkeypatch.setenv("HF_API_KEY", "complete-key-no-colon")
    plan = build_higgsfield_scenes(load_existing_story(), inspect_locked_character_refs())
    assert_higgsfield_live_authorized(
        series_slug="birko",
        episode_number=2,
        stage="higgsfield-scene-generate",
        confirm_paid=True,
        plan=plan,
        settings=_empty_settings(),
    )


def test_http_client_gets_complete_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_hf_env(monkeypatch)
    monkeypatch.setenv("HF_API_KEY", "complete-token")
    captured: dict[str, object] = {}

    class FakeResponse:
        content = b"{}"

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, str]:
            return {"id": "mock"}

    class FakeClient:
        def __init__(self, timeout: float | None = None) -> None:
            del timeout

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def post(self, url: str, headers: dict[str, str] | None = None, json=None):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr("httpx.Client", FakeClient)
    submit_higgsfield_json(
        url="https://example.invalid/bytedance/seedance-2.5/reference-to-video",
        body={"prompt": "x", "generate_audio": True},
        confirm_paid=True,
        settings=Settings(allow_paid_apis=True, _env_file=None),
    )
    headers = captured["headers"]
    assert isinstance(headers, dict)
    assert headers["Authorization"] == "Key complete-token"
    assert "complete-token" not in str(captured["url"])


def test_cli_preflight_does_not_print_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    if not Path(STORY_SPEC_RELATIVE).is_file():
        pytest.skip("checked-in story spec not available")
    _clear_hf_env(monkeypatch)
    monkeypatch.setenv("HF_API_KEY", _SECRET)
    result = CliRunner().invoke(
        app, ["birko-episode2", "--stage", "higgsfield-scene-preflight"]
    )
    assert result.exit_code == 0, result.output
    assert "higgsfield_credentials_present=true" in result.output
    assert "live_post_authorized=" in result.output
    assert _SECRET not in result.output
    assert "provider_http_calls=0" in result.output


def test_settings_split_still_works_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_hf_env(monkeypatch)
    cfg = Settings(
        higgsfield_api_key_id=SecretStr("from-settings-id"),
        higgsfield_api_key_secret=SecretStr("from-settings-secret"),
        _env_file=None,
    )
    assert resolve_higgsfield_api_key(cfg) == "from-settings-id:from-settings-secret"
