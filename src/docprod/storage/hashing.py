from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel


def _canonicalize(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _canonicalize(value.model_dump(mode="json"))
    if isinstance(value, Enum):
        return _canonicalize(value.value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        items = sorted(value.items(), key=lambda item: str(item[0]))
        return {str(key): _canonicalize(val) for key, val in items}
    if isinstance(value, (list, tuple)):
        return [_canonicalize(item) for item in value]
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise ValueError("NaN and Inf are not allowed in canonical JSON")
        return value
    if isinstance(value, str):
        return value
    raise TypeError(f"Unsupported type for canonical JSON: {type(value)!r}")


def canonical_json(value: Any) -> str:
    """Stable JSON for semantically identical structures (dict key order independent)."""
    return json.dumps(
        _canonicalize(value),
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )


def content_hash(value: Any) -> str:
    """SHA-256 hex digest of canonical JSON."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
