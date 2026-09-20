"""Vercel FastAPI zero-config entrypoint.

Vercel serves this ASGI `app` for every public path (not file-based /api routing).
Do not put the FastAPI app in api/index.py: that legacy layout only maps /api.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from docprod.api.app import app_from_settings  # noqa: E402

app = app_from_settings()
