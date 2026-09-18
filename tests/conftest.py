from __future__ import annotations

from pathlib import Path

import pytest

from docprod.storage import paths as pathmod


@pytest.fixture
def projects_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "projects"
    root.mkdir()
    monkeypatch.setattr(pathmod, "default_projects_root", lambda: root)
    monkeypatch.setattr(pathmod, "default_cache_root", lambda: tmp_path / "cache")
    monkeypatch.setattr(pathmod, "default_repo_root", lambda: tmp_path)
    return root
