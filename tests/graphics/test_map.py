from __future__ import annotations

from pathlib import Path

from docprod.graphics.map import compose_map_still, route_reveal
from docprod.graphics.renderer import execute_generate_graphic
from docprod.models.enums import AssetStrategy, Mood, TransitionType, VisualEffect
from docprod.models.scene import Scene
from docprod.storage.paths import ProjectPaths


def _map_scene() -> Scene:
    return Scene(
        id="scene_0012",
        start=0.0,
        end=1.0,
        duration=1.0,
        narration="Haritada işaretli rota kuzey kapısına gidiyordu.",
        visual_intent="Haritada işaretli rota kuzey kapısına gidiyordu.",
        asset_strategy=AssetStrategy.map,
        effect=VisualEffect.map_route,
        transition=TransitionType.cut,
        mood=Mood.mysterious,
        subtitle="harita",
        metadata={"primary_category": "map_or_travel"},
    )


def test_map_graphic_deterministic(tmp_path: Path) -> None:
    paths = ProjectPaths(root=tmp_path / "proj")
    scene = _map_scene()
    first = execute_generate_graphic(paths, scene=scene, seed=11)
    second = execute_generate_graphic(paths, scene=scene, seed=11)
    assert first.graphic_type == "map"
    assert first.output_sha256 == second.output_sha256
    assert paths.scene_map_base("scene_0012").is_file()
    assert paths.scene_map_bg("scene_0012").is_file()
    assert paths.scene_map_route("scene_0012").is_file()
    assert "Kuzey Kapısı" in first.text_fields["destination"]
    assert "T.C." not in " ".join(first.text_fields.values())


def test_route_reveal_is_smooth_and_monotonic() -> None:
    samples = [route_reveal(index / 100) for index in range(101)]
    assert samples[0] == 0.0
    assert samples[20] == 0.0
    assert samples[80] == 1.0
    assert samples[-1] == 1.0
    active = samples[21:80]
    assert all(b >= a for a, b in zip(active, active[1:], strict=False))
    assert len({round(value, 6) for value in active}) == len(active)


def test_map_still_includes_supported_label_only() -> None:
    still, background, overlay, mask, labels = compose_map_still(_map_scene(), seed="m")
    assert still.size == background.size
    assert overlay.mode == "RGBA"
    assert mask.mode == "L"
    assert labels["destination"] == "Kuzey Kapısı"
    assert "İstanbul" not in " ".join(labels.values())
