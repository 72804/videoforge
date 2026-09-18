from __future__ import annotations

from pathlib import Path

import pytest

from docprod.exceptions import UnsafeProjectIdError
from docprod.storage.paths import project_paths, validate_project_id


def test_safe_project_ids_accepted(tmp_path: Path) -> None:
    for project_id in ("demo", "atm_story_001", "DemoDoc"):
        assert validate_project_id(project_id) == project_id
        paths = project_paths(project_id, projects_root=tmp_path)
        assert paths.root == (tmp_path / project_id).resolve()
        assert paths.project_json.name == "project.json"


def test_path_traversal_ids_rejected(tmp_path: Path) -> None:
    for project_id in ("../../etc", "../etc", "foo/bar", "foo\\bar", "..", ".", ""):
        with pytest.raises(UnsafeProjectIdError):
            validate_project_id(project_id)
        with pytest.raises(UnsafeProjectIdError):
            project_paths(project_id, projects_root=tmp_path)
