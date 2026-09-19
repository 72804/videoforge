from __future__ import annotations

from pathlib import Path

from docprod.archive.base import ArchiveStillProvider
from docprod.storage.hashing import file_sha256
from docprod.storage.json_store import atomic_write_bytes


def download_archive_file(provider: ArchiveStillProvider, url: str, dest: Path) -> str:
    payload = provider.fetch_bytes(url)
    dest.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(dest, payload)
    return file_sha256(dest)
