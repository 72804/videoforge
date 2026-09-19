from __future__ import annotations

from docprod.models.enums import AssetStrategy, Mood, TransitionType, VisualEffect
from docprod.models.scene import GenerationSpec, Scene, ScenePlan
from docprod.production.balance import rebalance_scene_plan

G = AssetStrategy.generated_graphic


def _scene(n: int, strategy: AssetStrategy, narration: str, subject: str, start: float) -> Scene:
    prompt = "p" if strategy in {AssetStrategy.ai_image, AssetStrategy.ai_image_to_video} else None
    return Scene(
        id=f"scene_{n:04d}",
        start=start,
        end=start + 4.0,
        duration=4.0,
        narration=narration,
        visual_intent=subject,
        asset_strategy=strategy,
        effect=VisualEffect.none,
        transition=TransitionType.cut,
        mood=Mood.neutral,
        subtitle=narration,
        generation=GenerationSpec(image_prompt=prompt),
        metadata={
            "visual_subject": subject,
            "chapter": "HOOK",
            "graphic_brief": subject if strategy is G else "",
            "movement_need": "low",
        },
    )


def test_balance_breaks_graphic_run_and_keeps_named_off_ai() -> None:
    scenes = [
        _scene(1, G, "Federasyon 1966'da kuruldu ve kota sistemi geldi.", "1966 chart", 0),
        _scene(2, G, "Depodaki fıçılar ve koridor atmosferi.", "warehouse barrels", 4),
        _scene(3, G, "Fıçı depo koridoru tekrar.", "warehouse barrels", 8),
        _scene(4, G, "Yine depo fıçıları.", "warehouse barrels", 12),
        _scene(5, G, "Tazminat 9 milyon CAD mahkeme.", "court amount", 16),
        _scene(
            6,
            AssetStrategy.document,
            "Michel Gauvreau envanter kaydı.",
            "Michel Gauvreau sheet",
            20,
        ),
    ]
    plan = ScenePlan(project_id="p", scenes=scenes, total_duration=24.0)
    out = rebalance_scene_plan(plan)
    assert len(out.scenes) == 6
    strategies = [scene.asset_strategy for scene in out.scenes]
    assert strategies[0] is G
    assert G not in strategies[1:4]
    assert AssetStrategy.ai_image in strategies[1:4] or AssetStrategy.stock_video in strategies[1:4]
    assert out.scenes[5].asset_strategy is not AssetStrategy.ai_image
    run = 1
    max_run = 1
    for prev, curr in zip(out.scenes, out.scenes[1:], strict=False):
        same = prev.asset_strategy is curr.asset_strategy is G
        run = run + 1 if same else 1
        max_run = max(max_run, run)
    assert max_run < 6
