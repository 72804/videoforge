from __future__ import annotations

from pathlib import Path

from docprod.render.ffmpeg import ProbeInfo, probe_media
from docprod.storage.hashing import file_sha256


def cached_file_sha256(path: Path) -> str:
    return file_sha256(path)


def cached_probe(path: Path) -> ProbeInfo:
    return probe_media(path)


def poll_delays(*, initial: float = 5.0, cap: float = 20.0, max_wait: float = 900.0) -> list[float]:
    delays: list[float] = []
    elapsed = 0.0
    current = initial
    while elapsed < max_wait:
        delays.append(round(min(current, cap, max_wait - elapsed), 3))
        elapsed += delays[-1]
        current = min(cap, current * 1.5)
        if delays[-1] <= 0:
            break
    return delays
