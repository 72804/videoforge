from __future__ import annotations

import shutil
import subprocess


def probe_binary(name: str) -> tuple[bool, str | None, str | None]:
    """Return (available, path, first_version_line)."""
    path = shutil.which(name)
    if path is None:
        return False, None, None
    completed = subprocess.run(
        [path, "-version"],
        check=False,
        capture_output=True,
        text=True,
    )
    output = completed.stdout or completed.stderr
    first_line = output.splitlines()[0].strip() if output else None
    return True, path, first_line
