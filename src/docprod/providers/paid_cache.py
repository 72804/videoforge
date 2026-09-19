from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from docprod.storage.hashing import content_hash, file_sha256
from docprod.storage.json_store import load_json, save_json
from docprod.storage.paths import default_cache_root


def paid_cache_root() -> Path:
    return default_cache_root() / "paid"


def veo_request_hash(
    *,
    model: str,
    image_sha256: str,
    prompt: str,
    negative_prompt: str,
    duration_seconds: int,
    aspect_ratio: str,
    resolution: str,
    count: int,
) -> str:
    return content_hash(
        {
            "provider": "google",
            "kind": "veo",
            "model": model,
            "image_sha256": image_sha256,
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "duration_seconds": duration_seconds,
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
            "count": count,
        }
    )


def lyria_request_hash(
    *,
    model: str,
    prompt: str,
    image_sha256s: list[str],
    duration_hint_seconds: float,
    wav: bool,
) -> str:
    return content_hash(
        {
            "provider": "google",
            "kind": "lyria",
            "model": model,
            "prompt": prompt,
            "image_sha256s": image_sha256s,
            "duration_hint_seconds": duration_hint_seconds,
            "wav": wav,
        }
    )


class PaidArtifactCache:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or paid_cache_root()

    def _dir(self, kind: str, digest: str) -> Path:
        return self.root / kind / digest

    def get(self, kind: str, digest: str) -> tuple[Path, dict] | None:
        folder = self._dir(kind, digest)
        meta_path = folder / "meta.json"
        if not meta_path.is_file():
            return None
        meta = load_json(meta_path)
        if not isinstance(meta, dict):
            return None
        rel = str(meta.get("output") or "output.bin")
        output = folder / Path(rel).name
        if not output.is_file():
            return None
        if meta.get("output_sha256") and file_sha256(output) != meta["output_sha256"]:
            return None
        return output, meta

    def put(
        self,
        kind: str,
        digest: str,
        payload: bytes,
        *,
        suffix: str,
        meta: dict[str, str | int | float | bool],
    ) -> Path:
        folder = self._dir(kind, digest)
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / f"output{suffix}"
        dest.write_bytes(payload)
        record = dict(meta)
        record["output"] = dest.name
        record["output_sha256"] = file_sha256(dest)
        record["request_hash"] = digest
        record.setdefault("timestamp", datetime.now(UTC).isoformat())
        record.setdefault("status", "ok")
        save_json(folder / "meta.json", record)
        return dest
