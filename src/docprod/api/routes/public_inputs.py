from __future__ import annotations

import hmac

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from docprod.config import get_settings
from docprod.product.higgsfield_inputs import public_input_token, resolve_packaged_asset

router = APIRouter(tags=["public-inputs"])


@router.get("/public-inputs/{token}/{asset_id}", operation_id="getHiggsfieldPublicInput")
def get_higgsfield_public_input(token: str, asset_id: str) -> Response:
    """Token-gated JPEG for Higgsfield GET. No API keys. No predictable filenames."""
    expected = public_input_token(get_settings())
    if not expected or len(token) != len(expected) or not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=404, detail="not found")
    path = resolve_packaged_asset(asset_id)
    if path is None:
        raise HTTPException(status_code=404, detail="not found")
    return Response(content=path.read_bytes(), media_type="image/jpeg")
