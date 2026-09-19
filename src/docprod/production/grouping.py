from __future__ import annotations

from docprod.audio.script import tokenize_display
from docprod.models.enums import AssetStrategy
from docprod.models.scene import Scene, ScenePlan
from docprod.production import AssetUnit


def visual_concept_key(scene: Scene) -> str:
    subject = str(scene.metadata.get("visual_subject") or scene.visual_intent)
    tokens = tokenize_display(subject.casefold())[:8]
    return " ".join(tokens) or scene.id


def group_asset_units(plan: ScenePlan) -> list[AssetUnit]:
    units: list[AssetUnit] = []
    index = 0
    while index < len(plan.scenes):
        scene = plan.scenes[index]
        members = [scene]
        while index + len(members) < len(plan.scenes):
            nxt = plan.scenes[index + len(members)]
            if not _can_coalesce(members[-1], nxt):
                break
            members.append(nxt)
        units.append(_unit_from(members))
        index += len(members)
    return units


def _can_coalesce(left: Scene, right: Scene) -> bool:
    if left.asset_strategy is not right.asset_strategy:
        return False
    if visual_concept_key(left) != visual_concept_key(right):
        return False
    if str(left.metadata.get("chapter") or "") != str(right.metadata.get("chapter") or ""):
        return False
    if left.asset_strategy in {
        AssetStrategy.map,
        AssetStrategy.document,
        AssetStrategy.generated_graphic,
        AssetStrategy.text_card,
    }:
        return False
    return True


def _unit_from(members: list[Scene]) -> AssetUnit:
    first = members[0]
    last = members[-1]
    duration = round(sum(item.duration for item in members), 4)
    shared = len(members) > 1
    strategy = first.asset_strategy
    generation = strategy in {AssetStrategy.ai_image, AssetStrategy.ai_image_to_video}
    status = "UNRESOLVED"
    if strategy in {
        AssetStrategy.generated_graphic,
        AssetStrategy.document,
        AssetStrategy.map,
        AssetStrategy.text_card,
    }:
        status = "READY_LOCAL"
    elif strategy is AssetStrategy.stock_video:
        status = "UNRESOLVED"
    elif strategy in {AssetStrategy.archive_image, AssetStrategy.archive_video}:
        status = "UNRESOLVED"
    elif strategy is AssetStrategy.ai_image:
        status = "NEEDS_AI_IMAGE"
    elif strategy is AssetStrategy.ai_image_to_video:
        status = "NEEDS_AI_VIDEO"
    uid = f"au_{first.id.replace('scene_', '')}_{last.id.replace('scene_', '')}"
    if first.id == last.id:
        uid = f"au_{first.id.replace('scene_', '')}"
    return AssetUnit(
        asset_unit_id=uid,
        scene_ids=[item.id for item in members],
        source_strategy=strategy,
        continuous_duration=duration,
        visual_concept=visual_concept_key(first),
        generation_required=generation,
        provider="",
        reuse_mode="shared_continue" if shared else "unique",
        trim_policy="continuous" if shared else "per_scene_window",
        continuity_group=str(first.metadata.get("semantic_intent_id") or uid),
        estimated_cost="unresolved" if generation else "0",
        status=status,  # type: ignore[arg-type]
    )


def saved_generation_count(plan: ScenePlan, units: list[AssetUnit]) -> int:
    ai_scenes = sum(
        1
        for scene in plan.scenes
        if scene.asset_strategy in {AssetStrategy.ai_image, AssetStrategy.ai_image_to_video}
    )
    ai_units = sum(
        1
        for unit in units
        if unit.source_strategy in {AssetStrategy.ai_image, AssetStrategy.ai_image_to_video}
    )
    return max(0, ai_scenes - ai_units)
