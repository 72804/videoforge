from __future__ import annotations

from pathlib import Path

import pytest

from docprod.providers.google_lyria import preflight_lyria_request
from docprod.providers.music_base import MusicGenerateRequest


def test_lyria_preflight_rejects_empty_and_vocal_prompts(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="empty"):
        preflight_lyria_request(
            MusicGenerateRequest(prompt="  ", duration_hint_seconds=30, image_paths=[])
        )
    with pytest.raises(ValueError, match="INSTRUMENTAL"):
        preflight_lyria_request(
            MusicGenerateRequest(prompt="upbeat song", duration_hint_seconds=30, image_paths=[])
        )
    with pytest.raises(ValueError, match="vocals"):
        preflight_lyria_request(
            MusicGenerateRequest(
                prompt="INSTRUMENTAL ONLY documentary score",
                duration_hint_seconds=30,
                image_paths=[],
            )
        )
    image = tmp_path / "frame.jpg"
    image.write_bytes(b"not-an-image-but-suffix-ok")
    preflight_lyria_request(
        MusicGenerateRequest(
            prompt="INSTRUMENTAL ONLY. NO VOCALS. NO LYRICS.",
            duration_hint_seconds=90,
            image_paths=[image],
        )
    )
