from __future__ import annotations

from typing import Protocol

from docprod.archive.models import ArchiveCandidate


class ArchiveStillProvider(Protocol):
    name: str

    def search_files(self, query: str, *, limit: int = 12) -> list[ArchiveCandidate]: ...

    def file_info(self, title: str) -> ArchiveCandidate | None: ...

    def fetch_bytes(self, url: str) -> bytes: ...
