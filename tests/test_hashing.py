from __future__ import annotations

from datetime import UTC, datetime

from docprod.models.project import Project
from docprod.storage.hashing import canonical_json, content_hash


def test_canonical_hash_independent_of_dict_key_order() -> None:
    a = {"z": 1, "a": {"y": True, "x": [2, 1]}, "n": None}
    b = {"n": None, "a": {"x": [2, 1], "y": True}, "z": 1}
    assert canonical_json(a) == canonical_json(b)
    assert content_hash(a) == content_hash(b)
    assert len(content_hash(a)) == 64


def test_pydantic_model_hashing_deterministic() -> None:
    now = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    first = Project(
        id="hash_demo",
        title="Hash",
        language="en",
        target_duration_seconds=10,
        created_at=now,
        updated_at=now,
        metadata={"b": 2, "a": 1},
    )
    second = Project(
        id="hash_demo",
        title="Hash",
        language="en",
        target_duration_seconds=10,
        created_at=now,
        updated_at=now,
        metadata={"a": 1, "b": 2},
    )
    assert content_hash(first) == content_hash(second)
    assert content_hash(first) == content_hash(first.model_dump(mode="json"))
