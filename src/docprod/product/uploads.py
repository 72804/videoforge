from __future__ import annotations

import io

from PIL import Image, UnidentifiedImageError

from docprod.product.errors import UploadError

ALLOWED_MIME = {
    "image/jpeg": "JPEG",
    "image/png": "PNG",
    "image/webp": "WEBP",
}
MIN_SIDE = 32


def validate_image_bytes(
    data: bytes, *, max_bytes: int, declared_mime: str = ""
) -> tuple[int, int, str]:
    if not data:
        raise UploadError("empty upload")
    if len(data) > max_bytes:
        raise UploadError("upload too large")
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            width, height = image.size
            fmt = (image.format or "").upper()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise UploadError("invalid image") from exc
    mime = ""
    for candidate, label in ALLOWED_MIME.items():
        if fmt == label:
            mime = candidate
            break
    if not mime:
        raise UploadError("unsupported image type")
    if declared_mime and declared_mime not in ALLOWED_MIME:
        raise UploadError("unsupported image type")
    if min(width, height) < MIN_SIDE:
        raise UploadError("image too small")
    return width, height, mime
