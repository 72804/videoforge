from __future__ import annotations

from pathlib import Path
from typing import Protocol
from urllib.parse import quote


class StorageBackend(Protocol):
    def put_bytes(self, key: str, data: bytes, *, content_type: str = "") -> str: ...

    def get_bytes(self, key: str) -> bytes: ...

    def exists(self, key: str) -> bool: ...

    def url_for(self, key: str) -> str: ...


class LocalStorageBackend:
    """Development object storage. Future S3/R2 backends must match this interface."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        if ".." in Path(key).parts or key.startswith("/"):
            raise ValueError(f"unsafe storage key {key!r}")
        return self.root / key

    def put_bytes(self, key: str, data: bytes, *, content_type: str = "") -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        if content_type:
            path.with_suffix(path.suffix + ".ctype").write_text(content_type, encoding="utf-8")
        return key

    def get_bytes(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def url_for(self, key: str) -> str:
        return "file://" + quote(str(self._path(key).resolve()))


class MemoryStorageBackend:
    def __init__(self) -> None:
        self._blobs: dict[str, bytes] = {}

    def put_bytes(self, key: str, data: bytes, *, content_type: str = "") -> str:
        self._blobs[key] = data
        return key

    def get_bytes(self, key: str) -> bytes:
        return self._blobs[key]

    def exists(self, key: str) -> bool:
        return key in self._blobs

    def url_for(self, key: str) -> str:
        return f"memory://{key}"
