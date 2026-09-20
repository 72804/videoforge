from __future__ import annotations

from pathlib import Path
from typing import Protocol
from urllib.parse import quote


class StorageBackend(Protocol):
    def put_bytes(self, key: str, data: bytes, *, content_type: str = "") -> str: ...

    def get_bytes(self, key: str) -> bytes: ...

    def exists(self, key: str) -> bool: ...

    def url_for(self, key: str) -> str: ...

    def delete(self, key: str) -> None: ...

    def signed_url(
        self, key: str, *, expires_in: int = 3600, method: str = "GET"
    ) -> str | None: ...

    def metadata(self, key: str) -> dict[str, str]: ...


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

    def delete(self, key: str) -> None:
        path = self._path(key)
        if path.is_file():
            path.unlink()

    def signed_url(self, key: str, *, expires_in: int = 3600, method: str = "GET") -> str | None:
        return self.url_for(key)

    def metadata(self, key: str) -> dict[str, str]:
        path = self._path(key)
        return {"size": str(path.stat().st_size), "content_type": "application/octet-stream"}


class PlaceholderStorageBackend:
    """Production mock storage. Bytes are not persisted. /media must not imply a durable disk."""

    def put_bytes(self, key: str, data: bytes, *, content_type: str = "") -> str:
        return key

    def get_bytes(self, key: str) -> bytes:
        raise KeyError(key)

    def exists(self, key: str) -> bool:
        return False

    def url_for(self, key: str) -> str:
        return f"placeholder://{key}"

    def delete(self, key: str) -> None:
        return None

    def signed_url(self, key: str, *, expires_in: int = 3600, method: str = "GET") -> str | None:
        return None

    def metadata(self, key: str) -> dict[str, str]:
        return {}


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

    def delete(self, key: str) -> None:
        self._blobs.pop(key, None)

    def signed_url(self, key: str, *, expires_in: int = 3600, method: str = "GET") -> str | None:
        return f"memory://{key}?exp={expires_in}"

    def metadata(self, key: str) -> dict[str, str]:
        data = self._blobs[key]
        return {"size": str(len(data)), "content_type": "application/octet-stream"}
