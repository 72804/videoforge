from __future__ import annotations

from pathlib import Path

import pytest

from docprod.config import get_settings
from docprod.storage import paths as pathmod


@pytest.fixture(autouse=True)
def isolate_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep tests independent of a local .env with paid keys enabled."""
    monkeypatch.setenv("ALLOW_PAID_APIS", "false")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("PEXELS_API_KEY", "")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def projects_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "projects"
    root.mkdir()
    monkeypatch.setattr(pathmod, "default_projects_root", lambda: root)
    monkeypatch.setattr(pathmod, "default_cache_root", lambda: tmp_path / "cache")
    monkeypatch.setattr(pathmod, "default_repo_root", lambda: tmp_path)
    return root
