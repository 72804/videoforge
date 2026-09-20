from __future__ import annotations

from typing import Any

WORK_UNIT_ORDER = (
    "story",
    "scene_planning",
    "images",
    "video",
    "voice",
    "audio",
    "render",
    "upload",
    "script",
)


def is_work_unit(value: Any) -> bool:
    return isinstance(value, dict) and "completed" in value and "total" in value


def work_units(progress: dict[str, Any]) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []
    seen: set[str] = set()
    for label in WORK_UNIT_ORDER:
        counts = progress.get(label)
        if is_work_unit(counts):
            seen.add(label)
            units.append(_unit(label, counts))
    for label, counts in progress.items():
        if label in seen or not is_work_unit(counts):
            continue
        units.append(_unit(label, counts))
    return units


def _unit(label: str, counts: dict[str, Any]) -> dict[str, Any]:
    completed = int(counts["completed"])
    total = int(counts["total"])
    return {
        "label": label,
        "completed": completed,
        "total": total,
        "done": total > 0 and completed >= total,
    }


def progress_counts(progress: dict[str, Any]) -> dict[str, int]:
    return {key: int(val["completed"]) for key, val in progress.items() if is_work_unit(val)}
