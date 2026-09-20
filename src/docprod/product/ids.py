from __future__ import annotations

from uuid import UUID, uuid4


def new_id() -> str:
    return str(uuid4())


def parse_id(value: str) -> str:
    return str(UUID(value))
