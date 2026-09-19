from __future__ import annotations

from pathlib import Path

from docprod.providers.paid_cache import PaidArtifactCache, lyria_request_hash, veo_request_hash


def test_veo_hash_includes_material_inputs() -> None:
    a = veo_request_hash(
        model="veo-3.1-lite-generate-preview",
        image_sha256="aaa",
        prompt="p",
        negative_prompt="n",
        duration_seconds=8,
        aspect_ratio="16:9",
        resolution="720p",
        count=1,
    )
    b = veo_request_hash(
        model="veo-3.1-lite-generate-preview",
        image_sha256="bbb",
        prompt="p",
        negative_prompt="n",
        duration_seconds=8,
        aspect_ratio="16:9",
        resolution="720p",
        count=1,
    )
    assert a != b


def test_paid_cache_roundtrip(tmp_path: Path) -> None:
    cache = PaidArtifactCache(tmp_path / "paid")
    digest = veo_request_hash(
        model="m",
        image_sha256="x",
        prompt="p",
        negative_prompt="",
        duration_seconds=8,
        aspect_ratio="16:9",
        resolution="720p",
        count=1,
    )
    cache.put("veo", digest, b"video-bytes", suffix=".mp4", meta={"model": "m"})
    hit = cache.get("veo", digest)
    assert hit is not None
    path, meta = hit
    assert path.read_bytes() == b"video-bytes"
    assert meta["request_hash"] == digest
    other = lyria_request_hash(
        model="lyria-3.5",
        prompt="INSTRUMENTAL ONLY NO VOCALS",
        image_sha256s=["a"],
        duration_hint_seconds=90,
        wav=True,
    )
    assert cache.get("lyria", other) is None
