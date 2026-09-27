from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from tests.product.test_higgsfield_scenes import _refs, _spec

from docprod.api.app import create_app
from docprod.product.errors import ProductError
from docprod.product.higgsfield_inputs import (
    PUBLIC_INPUT_TOKEN,
    assert_https_input_url,
    assert_https_request_body,
    build_public_asset_map,
    collect_request_input_urls,
    preflight_input_urls,
)
from docprod.product.higgsfield_scenes import (
    I2V_SCENE_IDS,
    SIMPLE_I2V_MODEL,
    SIMPLE_PRIMARY_MODEL,
    build_higgsfield_scenes,
)
from docprod.providers.higgsfield import SEEDANCE_CONTRACTS
from docprod.quality.catalog import get_model


def test_local_paths_never_enter_request_body(tmp_path: Path) -> None:
    plan = build_higgsfield_scenes(_spec(), _refs(tmp_path), root=tmp_path)
    for scene in plan.scenes:
        blob = str(scene.request_body)
        assert "file://" not in blob
        assert "/Users/" not in blob
        assert "audio_urls" not in scene.request_body
        assert scene.generate_audio is True
        for url in collect_request_input_urls(scene.request_body):
            assert url.startswith("https://")
            assert "/hf-in/" in url
            assert "/api/v1/public-inputs/" not in url
        for asset in scene.input_assets:
            assert Path(asset["local_path"]).is_file()
            assert asset["remote_https_url"].startswith("https://")


def test_https_url_required() -> None:
    with pytest.raises(ProductError, match="https URL required"):
        assert_https_input_url("http://example.com/a.jpg")
    with pytest.raises(ProductError, match="local filesystem"):
        assert_https_input_url("/Users/ugurgenc/ref.jpg")
    with pytest.raises(ProductError, match="localhost"):
        assert_https_input_url("https://127.0.0.1/a.jpg")


def test_inaccessible_url_stops_before_paid() -> None:
    with pytest.raises(ProductError, match="STOP BEFORE PAID HTTP"):
        preflight_input_urls(
            ["https://videoforge-dusky.vercel.app/hf-in/x/y.jpg"],
            probe=lambda url: {
                "status_code": 404,
                "ok": False,
                "bytes": 0,
                "content_type": "text/plain",
            },
        )


def test_public_asset_mapping(tmp_path: Path) -> None:
    local = tmp_path / "ref_birko.jpg"
    Image.new("RGB", (32, 48), (10, 10, 10)).save(local, "JPEG")
    payload = build_public_asset_map(
        character_locals={"birko": str(local)},
        location_locals={},
        root=tmp_path,
        packaged_dir=tmp_path / "packaged",
    )
    row = payload["assets"][0]
    assert row["character_id"] == "birko"
    assert row["local_path"].endswith("ref_birko.jpg")
    assert row["remote_https_url"].startswith("https://")
    assert "/hf-in/" in row["remote_https_url"]
    assert "birko.jpg" not in row["remote_https_url"]


def test_i2v_and_r2v_routing_and_pricing(tmp_path: Path) -> None:
    plan = build_higgsfield_scenes(_spec(), _refs(tmp_path), root=tmp_path)
    by_id = {scene.scene_id: scene for scene in plan.scenes}
    assert by_id["HF1_hook_bill"].model == SIMPLE_I2V_MODEL
    assert "image_url" in by_id["HF1_hook_bill"].request_body
    assert "image_urls" not in by_id["HF1_hook_bill"].request_body
    assert by_id["HF3_birko_slips"].model == SIMPLE_I2V_MODEL
    assert "image_url" in by_id["HF3_birko_slips"].request_body
    assert "image_urls" not in by_id["HF3_birko_slips"].request_body
    assert by_id["HF7_kemal_pays"].model == SIMPLE_I2V_MODEL
    assert by_id["HF8_payoff"].model == SIMPLE_I2V_MODEL
    assert by_id["HF2_order_setup"].model == SIMPLE_PRIMARY_MODEL
    assert "image_urls" in by_id["HF2_order_setup"].request_body
    assert set(I2V_SCENE_IDS) <= set(by_id)
    i2v = get_model("seedance-2.5-image-to-video")
    r2v = get_model("seedance-2.5-reference-to-video")
    assert i2v is not None and i2v.pricing.value == 0.144
    assert r2v is not None and r2v.pricing.value == 0.1728
    assert plan.hard_cap_usd == 12.0
    assert plan.reserved_usd <= 12.0
    assert plan.expected_usd == 9.4464
    assert plan.reserved_usd == 11.6352
    assert SEEDANCE_CONTRACTS[SIMPLE_I2V_MODEL]["url"].endswith("image-to-video")


def test_token_gated_public_input_endpoint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    local = tmp_path / "ref_kemal.jpg"
    Image.new("RGB", (32, 48), (20, 20, 20)).save(local, "JPEG")
    payload = build_public_asset_map(
        character_locals={"kemal": str(local)},
        location_locals={},
        root=tmp_path,
        packaged_dir=tmp_path / "packaged",
    )
    asset_id = payload["assets"][0]["asset_id"]
    packaged = tmp_path / "packaged" / f"{asset_id}.jpg"
    from docprod.product import higgsfield_inputs as module

    monkeypatch.setattr(module, "packaged_input_dir", lambda: tmp_path / "packaged")
    monkeypatch.setattr(
        "docprod.api.routes.public_inputs.public_input_token",
        lambda settings=None: PUBLIC_INPUT_TOKEN,
    )
    client = TestClient(create_app())
    missing = client.get(f"/api/v1/public-inputs/wrong-token/{asset_id}.jpg")
    assert missing.status_code == 404
    ok = client.get(f"/api/v1/public-inputs/{PUBLIC_INPUT_TOKEN}/{asset_id}.jpg")
    assert ok.status_code == 200
    assert ok.headers["content-type"].startswith("image/")
    assert len(ok.content) == packaged.stat().st_size


def test_assert_https_request_body_rejects_file() -> None:
    with pytest.raises(ProductError):
        assert_https_request_body({"image_urls": ["file:///tmp/a.jpg"]})
