from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from docprod.product.canary_cost import (
    reserve_image_usd,
    reserve_script_usd,
    reserve_tts_usd,
    veo_cost,
)
from docprod.storage.hashing import file_sha256
from docprod.storage.paths import default_projects_root

CANARY_SLUG = "videoforge_local_canary"
CANARY_HARD_CAP_USD = 2.0
MIN_REAL_JPEG = 8_000
MIN_REAL_MEDIA = 8_000
RESUME_SPEC_VERSION = 1


def canary_root(root: Path | None = None) -> Path:
    return root if root is not None else default_projects_root() / CANARY_SLUG


def ledger_path(root: Path | None = None) -> Path:
    return canary_root(root) / "artifacts" / "review" / "paid_ledger.json"


def resume_spec_path(root: Path | None = None) -> Path:
    return canary_root(root) / "artifacts" / "review" / "resume_spec.json"


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


def jpeg_record(path: Path, *, role: str, scene_id: str | None = None) -> dict[str, Any]:
    from PIL import Image

    image = Image.open(path)
    return {
        "path": str(path),
        "role": role,
        "scene_id": scene_id,
        "timestamp": datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
        "bytes": path.stat().st_size,
        "dimensions": f"{image.size[0]}x{image.size[1]}",
        "sha256": file_sha256(path),
        "this_live_canary": True,
        "counted_in_committed_spend": True,
    }


def consecutive_scene_stills(root: Path | None = None) -> list[Path]:
    work = work_dir(root)
    stills: list[Path] = []
    for index in range(16):
        path = work / f"still_{index}.jpg"
        if is_real_jpeg(path):
            stills.append(path)
        else:
            break
    return stills


def ignored_still_files(root: Path | None = None, *, used: list[Path] | None = None) -> list[Path]:
    work = work_dir(root)
    adopted = {path.resolve() for path in (used or consecutive_scene_stills(root))}
    extras: list[Path] = []
    for path in sorted(work.glob("still_*.jpg")):
        if is_real_jpeg(path) and path.resolve() not in adopted:
            extras.append(path)
    return extras


def load_stage_a_plan(root: Path | None = None) -> dict[str, Any]:
    path = canary_root(root) / "artifacts" / "review" / "stage_a_plan.json"
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def load_script_payload(root: Path | None = None) -> dict[str, Any] | None:
    path = work_dir(root) / "script.json"
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    scenes = payload.get("scenes")
    if not isinstance(scenes, list) or len(scenes) < 2:
        return None
    return payload


def load_resume_spec(root: Path | None = None) -> dict[str, Any] | None:
    path = resume_spec_path(root)
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return None
    scenes = payload.get("scenes")
    if not isinstance(scenes, list) or len(scenes) < 2:
        return None
    return payload


def durable_downstream_spec(root: Path | None = None) -> dict[str, Any] | None:
    script = load_script_payload(root)
    if script is not None:
        return {
            "kind": "script.json",
            "script_response": "PRESENT",
            "path": str(work_dir(root) / "script.json"),
            "payload": script,
        }
    spec = load_resume_spec(root)
    if spec is not None:
        return {
            "kind": "resume_spec",
            "script_response": spec.get("script_response") or "LOST",
            "path": str(resume_spec_path(root)),
            "payload": spec,
        }
    return None


def build_resume_spec(root: Path | None = None) -> dict[str, Any]:
    stills = consecutive_scene_stills(root)
    plan = load_stage_a_plan(root)
    plan_scenes = plan.get("scenes") if isinstance(plan.get("scenes"), list) else []
    script = load_script_payload(root)
    scene_count = len(stills) if stills else int(plan.get("scene_count") or 0)
    if script is not None:
        scene_count = len(script["scenes"])
        source = "script.json"
        script_state = "PRESENT"
    elif stills:
        source = "reconstructed_from_live_stills"
        script_state = "LOST"
    else:
        source = "stage_a_plan"
        script_state = "NOT_STARTED"
    duration = float(plan.get("duration_seconds") or 24.0)
    per = round(duration / scene_count, 3) if scene_count else 8.0
    veo_index = 1 if scene_count > 1 else 0
    for index in range(scene_count):
        plan_row = plan_scenes[index] if index < len(plan_scenes) else {}
        if bool(plan_row.get("wants_video")):
            veo_index = index
            break
    if script is not None:
        for index, raw in enumerate(script["scenes"]):
            if isinstance(raw, dict) and raw.get("wants_video"):
                veo_index = index
                break
    scenes: list[dict[str, Any]] = []
    for index in range(scene_count):
        plan_row = plan_scenes[index] if index < len(plan_scenes) else {}
        script_row: dict[str, Any] = {}
        if script is not None:
            raw = script["scenes"][index]
            script_row = raw if isinstance(raw, dict) else {}
        still = stills[index] if index < len(stills) else None
        if script_row:
            prompt_source = "script.json"
        elif plan_row:
            prompt_source = "stage_a_plan_placeholder"
        else:
            prompt_source = "reconstructed_placeholder"
        scenes.append(
            {
                "order_index": index,
                "scene_id": str(index),
                "still_path": str(still) if still is not None else "",
                "sha256": file_sha256(still) if still is not None else "",
                "visual_prompt": str(
                    script_row.get("visual")
                    or plan_row.get("visual_prompt")
                    or "Cinematic still of Nolan. Original Luna visual prompt was not persisted."
                ),
                "motion_prompt": str(
                    script_row.get("motion") or plan_row.get("motion") or "subtle camera drift"
                ),
                "narration": str(
                    script_row.get("narration")
                    or plan_row.get("narration")
                    or "Original paid narration was not persisted."
                ),
                "duration_seconds": float(script_row.get("duration_seconds") or per),
                "wants_video": index == veo_index,
                "character": str(plan.get("character") or "Nolan"),
                "prompt_source": prompt_source,
            }
        )
    ignored = ignored_still_files(root, used=stills[:scene_count])
    return {
        "version": RESUME_SPEC_VERSION,
        "source": source,
        "script_response": script_state,
        "authoritative_scene_count": scene_count,
        "stage_a_scene_count": int(plan.get("scene_count") or 3),
        "mismatch_note": (
            "Stage A / CLI printed 3 scenes and 4 images (1 identity + 3 stills). "
            "The live paid run wrote four consecutive scene stills (still_0..still_3) "
            "during 03:27–03:28 into work/ and storage project 3838bb3b. "
            "Authoritative live scene count is therefore 4. "
            "The CLI summary used the pre-script Stage A plan, not the Luna output."
            if scene_count == 4 and int(plan.get("scene_count") or 3) == 3
            else ""
        ),
        "character": str(plan.get("character") or "Nolan"),
        "duration_seconds": (
            round(sum(row["duration_seconds"] for row in scenes), 3) if scenes else duration
        ),
        "scenes": scenes,
        "ignored_stills": [str(path) for path in ignored],
        "provider_http_calls": 0,
    }


def save_resume_spec(payload: dict[str, Any], root: Path | None = None) -> Path:
    path = resume_spec_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def discover_operations(root: Path | None = None) -> dict[str, dict[str, Any]]:
    """Zero-network reconstruction from local artifacts + ledger sidecar."""
    work = work_dir(root)
    stored = load_ledger(root).get("operations") or {}
    spec = load_resume_spec(root) or build_resume_spec(root)
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
    stills = consecutive_scene_stills(root)
    scene_count = int(spec.get("authoritative_scene_count") or len(stills))
    stills = stills[:scene_count]
    script_present = load_script_payload(root) is not None
    script_ok = script_present or bool(stills)
    merge(
        "script",
        {
            "state": (
                "SUCCEEDED"
                if script_present
                else "SUCCEEDED_RESPONSE_LOST"
                if stills
                else "NOT_STARTED"
            ),
            "provider": "openai",
            "model": "gpt-5.6-luna",
            "artifact": str(script_file) if script_file.is_file() else str(resume_spec_path(root)),
            "reserved_usd": reserve_script_usd(),
            "actual_usd": None,
            "safe_to_reuse": script_ok,
            "note": (
                ""
                if script_present
                else "paid JSON lost; downstream resume_spec is the durable source"
                if stills
                else ""
            ),
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
        if state in {"SUCCEEDED", "SUCCEEDED_RESPONSE_LOST"}:
            committed += float(actual) if actual is not None else reserved
        elif state in {"SUBMITTED", "RECOVERABLE", "UNCERTAIN"}:
            committed += reserved
        elif state in {"NOT_STARTED", "FAILED_UNBILLED", "PREPARED", "PENDING"}:
            remaining += reserved
    worst = round(committed + remaining, 6)
    return {
        "committed_usd": round(committed, 6),
        "remaining_reserved_usd": round(remaining, 6),
        "worst_case_usd": worst,
        "hard_cap_usd": CANARY_HARD_CAP_USD,
        "unspent_cap_usd": round(CANARY_HARD_CAP_USD - committed, 6),
        "unallocated_margin_usd": round(CANARY_HARD_CAP_USD - worst, 6),
    }


def format_status(
    operations: dict[str, dict[str, Any]],
    spend: dict[str, float],
    *,
    resume_spec: dict[str, Any] | None = None,
    inventory: list[dict[str, Any]] | None = None,
    root: Path | None = None,
) -> str:
    spec = resume_spec or {}
    labels = [
        ("script", "Script"),
        ("character_ref", "Character ref"),
    ]
    for index in range(int(spec.get("authoritative_scene_count") or 3)):
        labels.append((f"scene_still_{index + 1}", f"Scene still {index + 1}"))
    labels.extend([("veo", "Veo"), ("tts", "TTS"), ("render", "Render")])
    lines = [
        "LOCAL CANARY STATUS",
        f"Project: {CANARY_SLUG}",
        f"Authoritative scenes: {spec.get('authoritative_scene_count', 'n/a')}",
        f"Stage A scenes (pre-script): {spec.get('stage_a_scene_count', 3)}",
        "",
    ]
    uncertain = False
    blocked = False
    for key, title in labels:
        row = operations.get(key)
        if row is None:
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
    if inventory:
        lines.extend(["", "JPEG inventory"])
        for row in inventory:
            lines.append(
                f"- {row['role']} scene_id={row.get('scene_id')} "
                f"{row['dimensions']} sha256={row['sha256'][:12]}… "
                f"counted={row['counted_in_committed_spend']}"
            )
            lines.append(f"  {row['path']}")
    lines.extend(
        [
            "",
            f"Committed/reserved prior spend: ${spend['committed_usd']}",
            f"Remaining operation reservations: ${spend['remaining_reserved_usd']}",
            f"Worst-case total: ${spend['worst_case_usd']}",
            f"Unallocated safety margin: ${spend['unallocated_margin_usd']}",
            f"Hard cap: ${spend['hard_cap_usd']}",
            "",
        ]
    )
    veo = operations.get("veo") or {}
    remote = veo.get("remote_operation_id")
    if operations.get("script", {}).get("state") == "SUCCEEDED_RESPONSE_LOST" and load_resume_spec(
        root
    ) is None:
        blocked = True
        lines.append("Resume safety: BLOCKED: paid script JSON missing and no durable resume spec")
    elif uncertain:
        lines.append("Resume safety: BLOCKED: UNCERTAIN paid state")
    elif remote:
        lines.append(
            "Resume safety: BLOCKED: recover existing Veo remote id; do not submit"
        )
    elif spend["worst_case_usd"] - 1e-9 > spend["hard_cap_usd"]:
        lines.append("Resume safety: BLOCKED: worst-case exceeds $2 cap")
    elif blocked:
        lines.append("Resume safety: BLOCKED")
    else:
        lines.append("Resume safety: READY TO RESUME")
    return "\n".join(lines)


def jpeg_inventory(root: Path | None = None) -> list[dict[str, Any]]:
    work = work_dir(root)
    rows: list[dict[str, Any]] = []
    ref = work / "character_ref.jpg"
    if is_real_jpeg(ref):
        rows.append(jpeg_record(ref, role="character_ref", scene_id="character_ref"))
    spec = load_resume_spec(root) or build_resume_spec(root)
    used = consecutive_scene_stills(root)[: int(spec.get("authoritative_scene_count") or 0)]
    for index, path in enumerate(used):
        rows.append(jpeg_record(path, role=f"scene_still_{index + 1}", scene_id=str(index)))
    for path in ignored_still_files(root, used=used):
        row = jpeg_record(path, role="ignored_stale_still", scene_id=None)
        row["this_live_canary"] = False
        row["counted_in_committed_spend"] = False
        rows.append(row)
    return rows


def planned_resume_actions(operations: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    skip: list[str] = []
    run: list[str] = []
    mapping = [
        ("script", "script"),
        ("character_ref", "character reference"),
        ("scene_still_1", "scene still 1"),
        ("scene_still_2", "scene still 2"),
        ("scene_still_3", "scene still 3"),
        ("scene_still_4", "scene still 4"),
        ("veo", "Veo"),
        ("tts", "TTS"),
        ("render", "local audio + FFmpeg render"),
    ]
    for key, label in mapping:
        row = operations.get(key)
        if row is None:
            continue
        state = row["state"]
        if state in {"SUCCEEDED", "SUCCEEDED_RESPONSE_LOST"}:
            skip.append(label)
        elif state == "FAILED_UNBILLED":
            run.append(label)
        elif state in {"NOT_STARTED", "PREPARED", "PENDING"}:
            run.append(label)
        elif state in {"RECOVERABLE", "SUBMITTED"}:
            run.append(f"recover {label} (do not resubmit)")
    return {"skip": skip, "run": run}


def status_local_canary(root: Path | None = None) -> dict[str, Any]:
    spec = build_resume_spec(root)
    save_resume_spec(spec, root)
    operations = discover_operations(root)
    spend = spend_summary(operations)
    inventory = jpeg_inventory(root)
    actions = planned_resume_actions(operations)
    payload = {
        "slug": CANARY_SLUG,
        "operations": operations,
        "spend": spend,
        "resume_spec": spec,
        "inventory": inventory,
        "actions": actions,
        "provider_http_calls": 0,
        "text": format_status(
            operations, spend, resume_spec=spec, inventory=inventory, root=root
        ),
    }
    save_ledger(
        {"operations": operations, "spend": spend, "actions": actions, "resume_spec": spec},
        root,
    )
    return payload
