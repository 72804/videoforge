from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict

from docprod.config import Settings
from docprod.product.errors import ProductError
from docprod.storage.hashing import file_sha256

PUBLIC_INPUT_TOKEN = "n8vQ2wKmR7pL4xYcH1jF6tB9d"
DEFAULT_PUBLIC_ORIGIN = "https://videoforge-dusky.vercel.app"
PUBLIC_INPUT_PREFIX = "/hf-in"
PACKAGED_INPUTS_RELATIVE = "product/data/higgsfield_inputs"
MAPPING_RELATIVE = (
    "projects/birko_kemal_drama_canary/artifacts/render/episode_2/"
    "higgsfield_public_inputs.json"
)
NEXT_PUBLIC_RELATIVE = "apps/telegram-mini-app/public/hf-in"


class PublicAsset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    character_id: str = ""
    local_path: str = ""
    remote_https_url: str = ""
    sha256: str = ""
    asset_id: str = ""


def packaged_input_dir() -> Path:
    return Path(__file__).resolve().parent / "data" / "higgsfield_inputs"


def public_origin(settings: Settings | None = None) -> str:
    if settings is not None:
        raw = str(getattr(settings, "videoforge_public_origin", "") or "").strip()
        if not raw:
            raw = str(settings.telegram_mini_app_url or "").strip()
        if raw:
            return raw.rstrip("/")
    return DEFAULT_PUBLIC_ORIGIN


def public_input_token(settings: Settings | None = None) -> str:
    if settings is not None:
        secret = getattr(settings, "videoforge_public_input_token", None)
        if secret is not None:
            if hasattr(secret, "get_secret_value"):
                value = secret.get_secret_value().strip()
            else:
                value = str(secret).strip()
            if value:
                return value
    return PUBLIC_INPUT_TOKEN


def public_asset_url(*, origin: str, token: str, asset_id: str) -> str:
    return f"{origin.rstrip('/')}{PUBLIC_INPUT_PREFIX}/{token}/{asset_id}.jpg"


def assert_https_input_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        raise ProductError("STOP BEFORE PAID HTTP: empty input URL")
    if raw.startswith("file://") or raw.startswith("/") or raw.startswith("."):
        raise ProductError("STOP BEFORE PAID HTTP: local filesystem path cannot enter Higgsfield")
    parsed = urlparse(raw)
    host = (parsed.hostname or "").casefold()
    if parsed.scheme.casefold() != "https":
        raise ProductError(f"STOP BEFORE PAID HTTP: https URL required, got {raw!r}")
    if host in {"localhost", "127.0.0.1", "::1"}:
        raise ProductError(
            "STOP BEFORE PAID HTTP: localhost input URLs are not reachable by Higgsfield"
        )
    if not host:
        raise ProductError(f"STOP BEFORE PAID HTTP: invalid host in {raw!r}")
    return raw


def collect_request_input_urls(body: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    single = body.get("image_url")
    if isinstance(single, str) and single.strip():
        urls.append(single.strip())
    rows = body.get("image_urls")
    if isinstance(rows, list):
        urls.extend(str(item).strip() for item in rows if str(item).strip())
    extra = body.get("end_image_url")
    if isinstance(extra, str) and extra.strip():
        urls.append(extra.strip())
    return urls


def assert_https_request_body(body: dict[str, Any]) -> list[str]:
    urls = collect_request_input_urls(body)
    if not urls:
        raise ProductError("STOP BEFORE PAID HTTP: request has no image inputs")
    return [assert_https_input_url(url) for url in urls]


def default_url_probe(url: str) -> dict[str, Any]:
    import httpx

    headers = {"User-Agent": "VideoForge-HiggsfieldInputPreflight/1"}
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        response = client.get(url, headers=headers)
        content_type = str(response.headers.get("content-type") or "")
        body = response.content or b""
        return {
            "url": url,
            "status_code": int(response.status_code),
            "ok": response.is_success,
            "bytes": len(body),
            "content_type": content_type,
        }


def preflight_input_urls(
    urls: list[str],
    *,
    probe: Callable[[str], dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    checker = probe or default_url_probe
    rows: list[dict[str, Any]] = []
    for url in urls:
        assert_https_input_url(url)
        row = checker(url)
        status = int(row.get("status_code") or 0)
        size = int(row.get("bytes") or 0)
        ctype = str(row.get("content_type") or "").casefold()
        ok = bool(row.get("ok")) and 200 <= status < 300 and size > 0
        if "image" not in ctype and "octet-stream" not in ctype and "jpeg" not in ctype:
            ok = False
        rows.append({**row, "ok": ok})
        if not ok:
            raise ProductError(
                "STOP BEFORE PAID HTTP: input URL is not a reachable image: "
                f"{url} status={status} bytes={size} type={ctype}"
            )
    return rows


def _asset_id_for(path: Path) -> str:
    digest = file_sha256(path)
    return digest[:32]


def stage_public_asset_file(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and dest.stat().st_size == src.stat().st_size:
        return
    shutil.copy2(src, dest)


def build_public_asset_map(
    *,
    character_locals: dict[str, str],
    location_locals: dict[str, str],
    root: Path,
    settings: Settings | None = None,
    packaged_dir: Path | None = None,
) -> dict[str, Any]:
    origin = public_origin(settings)
    token = public_input_token(settings)
    packaged = packaged_dir or packaged_input_dir()
    next_dir = root / NEXT_PUBLIC_RELATIVE / token
    assets: list[dict[str, str]] = []
    for key, local in {**character_locals, **location_locals}.items():
        path = Path(local)
        if not path.is_file():
            continue
        asset_id = _asset_id_for(path)
        name = f"{asset_id}.jpg"
        stage_public_asset_file(path, packaged / name)
        stage_public_asset_file(path, next_dir / name)
        url = public_asset_url(origin=origin, token=token, asset_id=asset_id)
        assert_https_input_url(url)
        character_id = key if key in character_locals else ""
        assets.append(
            {
                "key": key,
                "character_id": character_id,
                "local_path": str(path.resolve()),
                "remote_https_url": url,
                "sha256": file_sha256(path),
                "asset_id": asset_id,
            }
        )
    payload = {
        "origin": origin,
        "token_name": "VIDEOFORGE_PUBLIC_INPUT_TOKEN",
        "hosting": "videoforge vercel static /hf-in/{token}/{asset_id}.jpg",
        "cleanup": (
            "After Higgsfield has fetched every scene input, rotate "
            "VIDEOFORGE_PUBLIC_INPUT_TOKEN, delete "
            "src/docprod/product/data/higgsfield_inputs/*.jpg and "
            f"{NEXT_PUBLIC_RELATIVE}/<token>/, then redeploy. Keep canonical local refs."
        ),
        "assets": assets,
    }
    mapping_path = root / MAPPING_RELATIVE
    mapping_path.parent.mkdir(parents=True, exist_ok=True)
    mapping_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    manifest = packaged / "manifest.json"
    packaged.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps({"token": token, "assets": [row["asset_id"] for row in assets]}, indent=2)
        + "\n",
        encoding="utf-8",
    )
    return payload


def asset_lookup(payload: dict[str, Any]) -> dict[str, PublicAsset]:
    out: dict[str, PublicAsset] = {}
    for row in payload.get("assets") or []:
        if not isinstance(row, dict):
            continue
        item = PublicAsset.model_validate(row)
        out[item.key] = item
    return out


def resolve_packaged_asset(asset_id: str) -> Path | None:
    token = asset_id.strip().removesuffix(".jpg")
    if not token.isalnum() or len(token) < 16:
        return None
    path = packaged_input_dir() / f"{token}.jpg"
    if path.is_file():
        return path
    return None
