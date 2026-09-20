"""Vercel Services FastAPI entrypoint. Reuses docprod.api.app_from_settings()."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_SRC = _REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from docprod.api.app import app_from_settings  # noqa: E402

app = app_from_settings()
