from __future__ import annotations

from docprod.models.enums import AssetStrategy, Mood, TransitionType, VisualEffect
from docprod.models.scene import GenerationSpec, Scene, ScenePlan

_DEMO_BEATS: list[dict[str, object]] = [
    {
        "duration": 3.2,
        "narration": "A commuter train hissed to a stop beneath the station clock.",
        "visual_intent": "Wide shot of a nearly empty regional train platform at dusk",
        "asset_strategy": AssetStrategy.stock_video,
        "effect": VisualEffect.pan_left,
        "transition": TransitionType.cut,
        "mood": Mood.neutral,
        "image_prompt": None,
    },
    {
        "duration": 2.8,
        "narration": "A man in a dark coat stepped off last, checking a folded timetable.",
        "visual_intent": "Man in a dark coat stepping off a train onto wet platform tiles",
        "asset_strategy": AssetStrategy.placeholder,
        "effect": VisualEffect.slow_push_in,
        "transition": TransitionType.cut,
        "mood": Mood.mysterious,
        "image_prompt": None,
    },
    {
        "duration": 3.5,
        "narration": "On a bench by the stairs sat an abandoned briefcase, upright and unclaimed.",
        "visual_intent": "Leather briefcase sitting alone on a wooden station bench",
        "asset_strategy": AssetStrategy.ai_image,
        "effect": VisualEffect.photo_table,
        "transition": TransitionType.cut,
        "mood": Mood.ominous,
        "image_prompt": (
            "cinematic documentary still, abandoned brown leather briefcase on a worn "
            "wooden train-station bench, dusk practical lighting, 35mm, no people"
        ),
    },
    {
        "duration": 2.5,
        "narration": "A paper luggage tag named a city he did not recognize.",
        "visual_intent": "Close-up of a handwritten luggage tag attached to the briefcase handle",
        "asset_strategy": AssetStrategy.document,
        "effect": VisualEffect.evidence_board,
        "transition": TransitionType.cut,
        "mood": Mood.tense,
        "image_prompt": None,
    },
    {
        "duration": 3.2,
        "narration": "He looked down the platform. No one came back for it.",
        "visual_intent": "Man turning to scan an empty platform as the train pulls away",
        "asset_strategy": AssetStrategy.stock_video,
        "effect": VisualEffect.documentary_handheld,
        "transition": TransitionType.cut,
        "mood": Mood.tense,
        "image_prompt": None,
    },
    {
        "duration": 2.8,
        "narration": "The station map placed this bench beside the unused north exit.",
        "visual_intent": "Schematic map of the station with a route to the north exit highlighted",
        "asset_strategy": AssetStrategy.map,
        "effect": VisualEffect.map_route,
        "transition": TransitionType.cut,
        "mood": Mood.mysterious,
        "image_prompt": None,
    },
    {
        "duration": 3.5,
        "narration": "Against his better judgment, he opened the clasps.",
        "visual_intent": "Hands opening brass clasps on the briefcase under overhead lamps",
        "asset_strategy": AssetStrategy.ai_image,
        "effect": VisualEffect.surveillance_zoom,
        "transition": TransitionType.cut,
        "mood": Mood.ominous,
        "image_prompt": (
            "cinematic documentary reenactment, close-up of hands opening an old briefcase "
            "on a station bench, tungsten overhead light, grain, no logos"
        ),
    },
    {
        "duration": 2.5,
        "narration": "Inside: a newspaper clipping, a key, and a photograph cut in half.",
        "visual_intent": "Flat-lay graphic of clipping, brass key, and torn photograph",
        "asset_strategy": AssetStrategy.generated_graphic,
        "effect": VisualEffect.newspaper_reveal,
        "transition": TransitionType.cut,
        "mood": Mood.chaotic,
        "image_prompt": None,
    },
    {
        "duration": 3.0,
        "narration": "He closed the case and walked toward the north stairs.",
        "visual_intent": "Silhouette of the man carrying the briefcase toward concrete stairs",
        "asset_strategy": AssetStrategy.placeholder,
        "effect": VisualEffect.silhouette_reveal,
        "transition": TransitionType.cut,
        "mood": Mood.urgent,
        "image_prompt": None,
    },
    {
        "duration": 3.0,
        "narration": "The platform was empty again, as if the briefcase had never been there.",
        "visual_intent": "Empty bench under the station clock after the man has left",
        "asset_strategy": AssetStrategy.stock_video,
        "effect": VisualEffect.slow_pull_out,
        "transition": TransitionType.dip_to_black,
        "mood": Mood.sad,
        "image_prompt": None,
    },
]


def build_demo_scene_plan(project_id: str, random_seed: int) -> ScenePlan:
    """Deterministic ~30s scene plan. No network, no generation."""
    scenes: list[Scene] = []
    cursor = 0.0
    for index, beat in enumerate(_DEMO_BEATS, start=1):
        duration = float(beat["duration"])
        start = round(cursor, 4)
        end = round(start + duration, 4)
        duration = round(end - start, 4)
        prompt = beat["image_prompt"]
        generation = GenerationSpec(
            image_prompt=str(prompt) if prompt else None,
            negative_prompt=None,
            motion_prompt=None,
            seed=random_seed + index if prompt else None,
        )
        narration = str(beat["narration"])
        scenes.append(
            Scene(
                id=f"scene_{index:04d}",
                start=start,
                end=end,
                duration=duration,
                narration=narration,
                visual_intent=str(beat["visual_intent"]),
                asset_strategy=beat["asset_strategy"],  # type: ignore[arg-type]
                effect=beat["effect"],  # type: ignore[arg-type]
                transition=beat["transition"],  # type: ignore[arg-type]
                mood=beat["mood"],  # type: ignore[arg-type]
                subtitle=narration,
                generation=generation,
                sources=[],
                metadata={"demo": True, "seed": random_seed},
            )
        )
        cursor = end
    return ScenePlan(
        project_id=project_id,
        scenes=scenes,
        total_duration=round(cursor, 4),
    )
