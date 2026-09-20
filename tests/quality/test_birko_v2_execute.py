from __future__ import annotations

from pathlib import Path

import pytest

from docprod.config import Settings
from docprod.providers.pricing import VEO_LITE_720P_USD_PER_SEC
from docprod.providers.runway_video import image_data_uri
from docprod.quality.locked import (
    BIRKO_V2_BALANCED_ROUTES,
    V2_BILLABLE_SECONDS,
    V2_EXPECTED_USD,
    V2_HARD_CAP_USD,
    V2_PRIORITY,
    V2_VEO_BILLABLE_SECONDS,
    VEO_LITE,
)
from docprod.quality.substitution import upgrade_clip_path
from docprod.storage.paths import ProjectPaths


def test_v2_locked_preflight_math() -> None:
    veo = V2_VEO_BILLABLE_SECONDS * VEO_LITE_720P_USD_PER_SEC
    assert V2_VEO_BILLABLE_SECONDS == pytest.approx(64.0)
    assert veo == pytest.approx(3.20)
    assert V2_EXPECTED_USD == pytest.approx(3.20)
    assert V2_EXPECTED_USD <= V2_HARD_CAP_USD
    assert set(BIRKO_V2_BALANCED_ROUTES.values()) == {VEO_LITE}
    assert all(seconds == 8 for seconds in V2_BILLABLE_SECONDS.values())
    assert V2_PRIORITY[0] == "b15"
    assert V2_PRIORITY[-1] == "b06"


def test_preflight_does_not_require_runway(monkeypatch: pytest.MonkeyPatch) -> None:
    from docprod.pipeline.execute_birko_v2 import preflight_v2

    monkeypatch.delenv("RUNWAY_API_KEY", raising=False)
    cfg = Settings(
        _env_file=None,
        allow_paid_apis=True,
        gemini_api_key="x",
        runway_api_key=None,
    )
    result = preflight_v2(cfg)
    assert result.ok is True
    assert result.expected_usd == pytest.approx(3.20)
    assert "Runway Gen-4.5: off" in "\n".join(result.lines)


def test_upgrade_clip_prefers_scene_then_beat(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    upgrades = paths.visuals_dir / "upgrades"
    upgrades.mkdir(parents=True)
    beat = upgrades / "b15.mp4"
    beat.write_bytes(b"beat")
    assert upgrade_clip_path(paths, "scene_0020", "b15") == beat
    scene = upgrades / "scene_0020.mp4"
    scene.write_bytes(b"scene")
    assert upgrade_clip_path(paths, "scene_0020", "b15") == scene


def test_runway_data_uri_from_still(tmp_path: Path) -> None:
    path = tmp_path / "still.jpg"
    path.write_bytes(b"\xff\xd8\xff\xd9")
    uri = image_data_uri(path)
    assert uri.startswith("data:image/jpeg;base64,")
