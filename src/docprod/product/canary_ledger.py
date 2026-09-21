from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from docprod.product.canary_cost import (
    reserve_image_usd,
    reserve_script_usd,
    reserve_tts_usd,
    veo_cost,
)
from docprod.storage.paths import default_projects_root

CANARY_SLUG = "videoforge_local_canary"
CANARY_HARD_CAP_USD = 2.0
MIN_REAL_JPEG = 8_000
MIN_REAL_MEDIA = 8_000


def canary_root(root: Path | None = None) -> Path:
    return root if root is not None else default_projects_root() / CANARY_SLUG


def ledger_path(root: Path | None = None) -> Path:
    return canary_root(root) / "artifacts" / "review" / "paid_ledger.json"


def work_dir(root: Path | None = None) -> Path:
    return canary_root(root) / "artifacts" / "work"


def is_real_jpeg(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size < MIN_REAL_JPEG:
        return False
    return path.read_bytes()[:3] == b"\xff\xd8\xff"


def is_real_media(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size < MIN_REAL_MEDIA:
        return False
    data = path.read_bytes()[:12]
    return not (data.startswith(b"fake") or data.startswith(b"dry-run"))


def load_ledger(root: Path | None = None) -> dict[str, Any]:
    path = ledger_path(root)
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def save_ledger(payload: dict[str, Any], root: Path | None = None) -> Path:
    path = ledger_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def discover_operations(root: Path | None = None) -> dict[str, dict[str, Any]]:
    """Zero-network reconstruction from local artifacts + ledger sidecar."""
    work = work_dir(root)
    stored = load_ledger(root).get("operations") or {}
    ops: dict[str, dict[str, Any]] = {}

    def merge(name: str, default: dict[str, Any]) -> None:
        prior = stored.get(name) if isinstance(stored.get(name), dict) else {}
        row = dict(default)
        for key, value in prior.items():
            if value not in (None, "", []) and key not in {"state", "safe_to_reuse"}:
                row[key] = value
        if prior.get("remote_operation_id"):
            row["remote_operation_id"] = prior["remote_operation_id"]
            row["state"] = "RECOVERABLE"
        elif default.get("state") == "SUCCEEDED":
            row["state"] = "SUCCEEDED"
        elif prior.get("state") == "UNCERTAIN":
            row["state"] = "UNCERTAIN"
        ops[name] = row

    script_file = work / "script.json"
    stills = sorted(
        path for path in work.glob("still_*.jpg") if is_real_jpeg(path)
    )
    script_ok = script_file.is_file() or bool(stills)
    merge(
        "script",
        {
            "state": "SUCCEEDED" if script_ok else "NOT_STARTED",
            "provider": "openai",
            "model": "gpt-5.6-luna",
            "artifact": str(script_file) if script_file.is_file() else "",
            "reserved_usd": reserve_script_usd(),
            "actual_usd": None,
            "safe_to_reuse": script_ok,
        },
    )
    ref = work / "character_ref.jpg"
    merge(
        "character_ref",
        {
            "state": "SUCCEEDED" if is_real_jpeg(ref) else "NOT_STARTED",
            "provider": "openai",
            "model": "gpt-image-2.5-flare",
            "artifact": str(ref) if is_real_jpeg(ref) else "",
            "reserved_usd": reserve_image_usd(with_reference=False),
            "actual_usd": None,
            "safe_to_reuse": is_real_jpeg(ref),
        },
    )
    for index, path in enumerate(stills):
        merge(
            f"scene_still_{index + 1}",
            {
                "state": "SUCCEEDED",
                "provider": "openai",
                "model": "gpt-image-2.5-flare",
                "artifact": str(path),
                "reserved_usd": reserve_image_usd(with_reference=is_real_jpeg(ref)),
                "actual_usd": None,
                "safe_to_reuse": True,
            },
        )
    veo_files = [path for path in work.glob("video_*.mp4") if is_real_media(path)]
    if veo_files:
        veo_state = "SUCCEEDED"
        note = ""
    elif stills:
        veo_state = "FAILED_UNBILLED"
        note = "local preflight rejected 9:16 before HTTP"
    else:
        veo_state = "NOT_STARTED"
        note = ""
    merge(
        "veo",
        {
            "state": veo_state,
            "provider": "google",
            "model": "veo-3.1-lite-generate-preview",
            "artifact": str(veo_files[0]) if veo_files else "",
            "remote_operation_id": None,
            "reserved_usd": veo_cost(8),
            "actual_usd": None,
            "safe_to_reuse": bool(veo_files),
            "note": note,
        },
    )
    tts = work / "tts.wav"
    merge(
        "tts",
        {
            "state": "SUCCEEDED" if is_real_media(tts) else "NOT_STARTED",
            "provider": "openai",
            "model": "gpt-4o-mini-tts",
            "artifact": str(tts) if is_real_media(tts) else "",
            "reserved_usd": reserve_tts_usd(),
            "actual_usd": None,
            "safe_to_reuse": is_real_media(tts),
        },
    )
    final = canary_root(root) / "artifacts" / "render" / "final" / "documentary_preview.mp4"
    merge(
        "render",
        {
            "state": "SUCCEEDED" if is_real_media(final) else "NOT_STARTED",
            "provider": "ffmpeg",
            "model": "ffmpeg",
            "artifact": str(final) if is_real_media(final) else "",
            "reserved_usd": 0.0,
            "actual_usd": 0.0,
            "safe_to_reuse": is_real_media(final),
        },
    )
    return ops


def spend_summary(operations: dict[str, dict[str, Any]]) -> dict[str, float]:
    committed = 0.0
    remaining = 0.0
    for row in operations.values():
        reserved = float(row.get("reserved_usd") or 0.0)
        actual = row.get("actual_usd")
        state = str(row.get("state") or "NOT_STARTED")
        if state == "SUCCEEDED":
            committed += float(actual) if actual is not None else reserved
        elif state in {"SUBMITTED", "RECOVERABLE", "UNCERTAIN"}:
            committed += reserved
        elif state in {"NOT_STARTED", "FAILED_UNBILLED", "PREPARED", "PENDING"}:
            remaining += reserved
    return {
        "committed_usd": round(committed, 6),
        "remaining_reserved_usd": round(remaining, 6),
        "worst_case_usd": round(committed + remaining, 6),
        "hard_cap_usd": CANARY_HARD_CAP_USD,
        "headroom_usd": round(CANARY_HARD_CAP_USD - committed, 6),
    }


def format_status(operations: dict[str, dict[str, Any]], spend: dict[str, float]) -> str:
    labels = [
        ("script", "Script"),
        ("character_ref", "Character ref"),
        ("scene_still_1", "Scene still 1"),
        ("scene_still_2", "Scene still 2"),
        ("scene_still_3", "Scene still 3"),
        ("scene_still_4", "Scene still 4"),
        ("veo", "Veo"),
        ("tts", "TTS"),
        ("render", "Render"),
    ]
    lines = ["LOCAL CANARY STATUS", f"Project: {CANARY_SLUG}", ""]
    uncertain = False
    for key, title in labels:
        row = operations.get(key)
        if row is None:
            if key == "scene_still_4":
                continue
            lines.append(f"{title}: NOT_STARTED")
            continue
        state = row["state"]
        extra = row.get("note") or ""
        cost = row.get("actual_usd")
        if cost is None:
            cost = row.get("reserved_usd")
        suffix = f" / cost ${cost}" if cost not in {None, ""} else ""
        detail = f" ({extra})" if extra else ""
        lines.append(f"{title}: {state}{suffix}{detail}")
        if state == "UNCERTAIN":
            uncertain = True
    lines.extend(
        [
            "",
            f"Known/reserved spend: ${spend['committed_usd']}",
            f"Remaining planned maximum: ${spend['remaining_reserved_usd']}",
            f"Worst-case total: ${spend['worst_case_usd']}",
            f"Hard cap: ${spend['hard_cap_usd']}",
            f"Remaining cap headroom: ${spend['headroom_usd']}",
            "",
        ]
    )
    veo = operations.get("veo") or {}
    remote = veo.get("remote_operation_id")
    if uncertain:
        lines.append("Resume safety: BLOCKED: UNCERTAIN paid state")
    elif remote:
        lines.append(
            "Resume safety: BLOCKED: recover existing Veo remote id; do not submit"
        )
    elif spend["worst_case_usd"] - 1e-9 > spend["hard_cap_usd"]:
        lines.append("Resume safety: BLOCKED: worst-case exceeds $2 cap")
    else:
        lines.append("Resume safety: READY TO RESUME")
    return "\n".join(lines)


def status_local_canary(root: Path | None = None) -> dict[str, Any]:
    operations = discover_operations(root)
    spend = spend_summary(operations)
    payload = {
        "slug": CANARY_SLUG,
        "operations": operations,
        "spend": spend,
        "provider_http_calls": 0,
        "text": format_status(operations, spend),
    }
    save_ledger({"operations": operations, "spend": spend}, root)
    return payload
