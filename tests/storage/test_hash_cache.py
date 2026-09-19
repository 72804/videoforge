from __future__ import annotations

from pathlib import Path

from docprod.storage.hashing import file_sha256


def test_file_sha256_reuses_identity_cache(tmp_path: Path) -> None:
    path = tmp_path / "blob.bin"
    path.write_bytes(b"hello" * 1000)
    first = file_sha256(path)
    second = file_sha256(path)
    assert first == second
    path.write_bytes(b"changed")
    third = file_sha256(path)
    assert third != first
