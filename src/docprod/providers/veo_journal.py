from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from docprod.storage.json_store import load_json, save_json

REQUEST_SUBMITTED = "REQUEST_SUBMITTED"
GENERATION_IN_PROGRESS = "GENERATION_IN_PROGRESS"
GENERATION_SUCCEEDED_REMOTE = "GENERATION_SUCCEEDED_REMOTE"
DOWNLOAD_FAILED = "DOWNLOAD_FAILED"
DOWNLOAD_SUCCEEDED = "DOWNLOAD_SUCCEEDED"
LOCAL_VALIDATION_SUCCEEDED = "LOCAL_VALIDATION_SUCCEEDED"
CACHE_COMMITTED = "CACHE_COMMITTED"
REMOTE_ARTIFACT_EXPIRED = "REMOTE_ARTIFACT_EXPIRED"

DOWNLOADABLE_STATES = frozenset({GENERATION_SUCCEEDED_REMOTE, DOWNLOAD_FAILED})


def ops_dir(cache_root: Path) -> Path:
    return cache_root / "veo_ops"


def journal_path(cache_root: Path, digest: str) -> Path:
    return ops_dir(cache_root) / f"{digest}.json"


def load_journal(cache_root: Path, digest: str) -> dict[str, Any] | None:
    path = journal_path(cache_root, digest)
    if not path.is_file():
        return None
    payload = load_json(path)
    return payload if isinstance(payload, dict) else None


def write_journal(cache_root: Path, digest: str, payload: dict[str, Any]) -> Path:
    path = journal_path(cache_root, digest)
    record = dict(payload)
    record["request_hash"] = digest
    record["updated_at"] = datetime.now(UTC).isoformat()
    save_json(path, record)
    return path


def remote_expired(payload: dict[str, Any], *, now: datetime | None = None) -> bool:
    raw = str(payload.get("expiration_time") or "").strip()
    if not raw:
        return False
    stamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    current = now or datetime.now(UTC)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current > stamp
