from __future__ import annotations

from pathlib import Path

import pytest
from tests.render.helpers import mini_plan, mini_scene

from docprod.exceptions import ZeroPlaceholderError
from docprod.graphics.renderer import execute_generate_graphic
from docprod.models.enums import AssetStrategy, Mood, TransitionType, VisualEffect
from docprod.models.scene import Scene, ScenePlan
from docprod.pipeline.inspect_assets import inspect_assets, require_zero_placeholders
from docprod.storage.paths import ProjectPaths


def test_inspect_assets_reports_placeholder(tmp_path: Path) -> None:
    paths = ProjectPaths(root=tmp_path / "proj")
    scene = mini_scene("scene_0001", 0.0, 0.4)
    rows = inspect_assets(paths, mini_plan(scene))
    assert rows[0].source_type == "placeholder"
    with pytest.raises(ZeroPlaceholderError, match="scene_0001"):
        require_zero_placeholders(paths, mini_plan(scene))


def test_inspect_assets_local_document(tmp_path: Path) -> None:
    paths = ProjectPaths(root=tmp_path / "proj")
    scene = Scene(
        id="scene_0008",
        start=0.0,
        end=0.4,
        duration=0.4,
        narration="polise haber verdi ve çantanın içindeki raporu yüksek sesle",
        visual_intent="report",
        asset_strategy=AssetStrategy.document,
        effect=VisualEffect.newspaper_reveal,
        transition=TransitionType.cut,
        mood=Mood.neutral,
        subtitle="report",
        metadata={"primary_category": "document"},
    )
    execute_generate_graphic(paths, scene=scene, seed=7)
    plan = ScenePlan(project_id="tiny", scenes=[scene], total_duration=0.4)
    rows = require_zero_placeholders(paths, plan)
    assert rows[0].source_type == "local_graphic"
    assert rows[0].source_label == "document"
    assert rows[0].provider == "local"
    assert Path(rows[0].artifact_path).is_file()
