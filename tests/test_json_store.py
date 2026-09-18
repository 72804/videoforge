from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from docprod.models.project import Project
from docprod.storage.json_store import atomic_write_bytes, atomic_write_text, load_model, save_model


def test_model_json_roundtrip(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    project = Project(
        id="roundtrip_one",
        title="Roundtrip",
        language="tr",
        target_duration_seconds=30,
        created_at=now,
        updated_at=now,
        random_seed=7,
        metadata={"k": "v"},
    )
    path = tmp_path / "project.json"
    save_model(path, project)
    loaded = load_model(path, Project)
    assert loaded.id == project.id
    assert loaded.title == project.title
    assert loaded.metadata == {"k": "v"}
    assert loaded.random_seed == 7


def test_atomic_write_replaces_destination(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "file.json"
    atomic_write_text(path, '{"a": 1}\n')
    assert path.read_text(encoding="utf-8") == '{"a": 1}\n'
    atomic_write_text(path, '{"a": 2}\n')
    assert path.read_text(encoding="utf-8") == '{"a": 2}\n'
    leftovers = list(path.parent.glob("*.tmp"))
    assert leftovers == []


def test_atomic_write_bytes(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "image.jpg"
    atomic_write_bytes(path, b"hello")
    assert path.read_bytes() == b"hello"
    atomic_write_bytes(path, b"world")
    assert path.read_bytes() == b"world"
    leftovers = list(path.parent.glob("*.tmp"))
    assert leftovers == []
