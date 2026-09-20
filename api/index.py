"""Vercel FastAPI entrypoint.

The FastAPI framework preset serves the whole ASGI app (not file-based /api routing).
Routes remain /health, /ready, /telegram/webhook, /api/v1/*.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from docprod.api.app import app_from_settings  # noqa: E402

app = app_from_settings()
