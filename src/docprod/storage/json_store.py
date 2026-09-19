from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from pydantic import BaseModel


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write binary data atomically via a temp file in the same directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def atomic_write_text(path: Path, text: str) -> None:
    """Write UTF-8 text atomically via a temp file in the same directory."""
    if path.is_file():
        try:
            if path.read_text(encoding="utf-8") == text:
                return
        except OSError:
            pass
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def save_json(path: Path, payload: object) -> None:
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    atomic_write_text(path, text)


def load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def save_model(path: Path, model: BaseModel) -> None:
    save_json(path, model.model_dump(mode="json"))


def load_model[T: BaseModel](path: Path, model_type: type[T]) -> T:
    data = load_json(path)
    return model_type.model_validate(data)
