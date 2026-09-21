from __future__ import annotations

from dataclasses import dataclass, field

from docprod.product.canary_cost import (
    CHARACTER_REF_SCENE_ID,
    reserve_image_usd,
    reserve_script_usd,
    reserve_tts_usd,
    veo_cost,
)
from docprod.product.enums import DurationMode, PlanItemType, ReferenceMode
from docprod.product.models import (
    Character,
    CharacterReference,
    GenerationPlan,
    GenerationPlanItem,
    Project,
    Scene,
    SceneVersion,
    ScriptVersion,
)
from docprod.product.plans import PricingPolicy, assemble_plan
from docprod.product.repository import MemoryRepository
from docprod.quality.enums import QualityProfile, SceneProductionClass
from docprod.quality.router import (
    preferred_video_model,
    still_route,
    wants_video,
)
from docprod.quality.specs import CharacterProfile, CharacterReferenceSet, SceneValueScore

CANARY_MIN_SECONDS = 15.0
CANARY_MAX_SECONDS = 30.0
CANARY_MIN_SCENES = 2
CANARY_MAX_SCENES = 5
CANARY_AUTO_SECONDS = 24.0
CANARY_AUTO_SCENES = 3
CANARY_MAX_VIDEO_SHOTS = 1

FIRST_CANARY_PROVIDERS = {
    "script": "openai",
    "script_model": "gpt-5.6-luna",
    "image": "openai",
    "image_model": "gpt-image-2.5-flare",
    "video": "google",
    "video_model": "veo-3.1-lite-generate-preview",
    "tts": "openai",
    "tts_model": "gpt-4o-mini-tts",
    "music": "local",
    "music_model": "procedural-sfx",
    "render": "ffmpeg",
    "render_model": "ffmpeg",
}


@dataclass(frozen=True)
class EngineSceneSpec:
    order_index: int
    visual_prompt: str
    motion_prompt: str
    narration: str
    duration_seconds: float
    production_class: SceneProductionClass
    image_model: str
    video_model: str
    wants_video: bool
    character_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class EngineProjectSpec:
    content_kind: str
    duration_seconds: float
    scene_count: int
    quality_profile: QualityProfile
    aspect_ratio: str
    language: str
    characters: CharacterReferenceSet
    scenes: tuple[EngineSceneSpec, ...]
    frozen_items: tuple[GenerationPlanItem, ...]
    estimated_provider_usd: float
    hard_max_usd: float


def parse_quality_profile(raw: str) -> QualityProfile:
    token = (raw or "balanced").strip().lower()
    try:
        return QualityProfile(token)
    except ValueError:
        return QualityProfile.BALANCED


def canary_duration(project: Project) -> tuple[float, int]:
    if project.duration_mode is DurationMode.AUTO:
        return CANARY_AUTO_SECONDS, CANARY_AUTO_SCENES
    target = float(project.target_duration_seconds or CANARY_AUTO_SECONDS)
    clamped = min(CANARY_MAX_SECONDS, max(CANARY_MIN_SECONDS, target))
    scenes = int(round(clamped / 8.0))
    scenes = min(CANARY_MAX_SCENES, max(CANARY_MIN_SCENES, scenes))
    return clamped, scenes


def map_character_set(
    project: Project,
    characters: list[Character],
    references: list[CharacterReference],
) -> CharacterReferenceSet:
    by_character: dict[str, list[CharacterReference]] = {}
    for ref in references:
        by_character.setdefault(ref.character_id, []).append(ref)
    profiles: list[CharacterProfile] = []
    for character in characters:
        refs = by_character.get(character.id, [])
        custom = [ref.storage_key for ref in refs if ref.mode is ReferenceMode.CUSTOM]
        generated = [ref.storage_key for ref in refs if ref.mode is not ReferenceMode.CUSTOM]
        primary = ""
        if character.primary_reference_id:
            match = next((ref for ref in refs if ref.id == character.primary_reference_id), None)
            if match:
                primary = match.storage_key
        if not primary and refs:
            primary = refs[0].storage_key
        locked = bool(character.locked_identity or custom)
        profiles.append(
            CharacterProfile(
                character_id=character.id,
                name=character.name,
                description=character.description,
                canonical_refs=custom or generated,
                appearance_notes=character.description,
                locked=locked,
                custom_references=custom,
                generated_references=generated,
                primary_reference=primary,
                reference_mode=(ReferenceMode.CUSTOM if custom else ReferenceMode.AUTO_GENERATED),
            )
        )
    return CharacterReferenceSet(project_id=project.id, profiles=profiles)


def classify_beat(index: int, total: int, prompt: str) -> SceneProductionClass:
    lowered = prompt.lower()
    if index == 0:
        return SceneProductionClass.ESTABLISHING_SHOT
    if index == total - 1:
        return SceneProductionClass.STATIC_CINEMATIC
    if any(word in lowered for word in ("talk", "say", "dialogue", "ask")):
        return SceneProductionClass.DIALOGUE_SHOT
    if any(word in lowered for word in ("run", "chase", "turn", "look")):
        return SceneProductionClass.SIMPLE_MOTION
    if index == 1 and total >= 3:
        return SceneProductionClass.REACTION_SHOT
    return SceneProductionClass.STATIC_CINEMATIC


def beat_scores(klass: SceneProductionClass) -> SceneValueScore:
    motion = {
        SceneProductionClass.SIMPLE_MOTION: 0.8,
        SceneProductionClass.REACTION_SHOT: 0.7,
        SceneProductionClass.DIALOGUE_SHOT: 0.45,
        SceneProductionClass.HERO_CINEMATIC: 0.85,
        SceneProductionClass.ESTABLISHING_SHOT: 0.4,
        SceneProductionClass.STATIC_CINEMATIC: 0.15,
    }.get(klass, 0.3)
    dialogue = 0.8 if klass is SceneProductionClass.DIALOGUE_SHOT else 0.2
    return SceneValueScore(
        story_importance=0.7,
        motion_need=motion,
        dialogue_importance=dialogue,
        performance_precision=0.2,
        character_importance=0.8,
    )


def route_scene(
    *,
    klass: SceneProductionClass,
    profile: QualityProfile,
    scores: SceneValueScore,
    remaining_video_slots: int,
) -> tuple[str, str, bool]:
    still = still_route("plan", klass, profile)
    image_model = still.selected_model
    video = wants_video(klass, scores, profile) and remaining_video_slots > 0
    if not video:
        return image_model, "local-camera", False
    return image_model, preferred_video_model(klass, profile), True


def build_engine_spec(
    project: Project,
    *,
    characters: list[Character],
    references: list[CharacterReference],
    hard_max_usd: float,
    pricing: PricingPolicy | None = None,
) -> EngineProjectSpec:
    policy = pricing or PricingPolicy()
    profile = parse_quality_profile(project.quality_profile)
    duration, scene_count = canary_duration(project)
    per_scene = round(duration / scene_count, 3)
    refs = map_character_set(project, characters, references)
    char_ids = [row.character_id for row in refs.profiles]
    remaining_video = CANARY_MAX_VIDEO_SHOTS if profile is not QualityProfile.ECONOMY else 0
    needs_generated_ref = bool(char_ids) and not any(
        profile.custom_references or profile.generated_references for profile in refs.profiles
    )
    scenes: list[EngineSceneSpec] = []
    items: list[GenerationPlanItem] = [
        GenerationPlanItem(
            type=PlanItemType.SCRIPT,
            model=FIRST_CANARY_PROVIDERS["script_model"],
            quantity=1,
            estimated_provider_usd=reserve_script_usd(),
            customer_stars=0,
        )
    ]
    if needs_generated_ref:
        items.append(
            GenerationPlanItem(
                type=PlanItemType.STILL,
                model=FIRST_CANARY_PROVIDERS["image_model"],
                quantity=1,
                estimated_provider_usd=reserve_image_usd(with_reference=False),
                customer_stars=0,
                scene_id=CHARACTER_REF_SCENE_ID,
            )
        )
    for index in range(scene_count):
        klass = classify_beat(index, scene_count, project.prompt)
        scores = beat_scores(klass)
        image_model, video_model, animate = route_scene(
            klass=klass,
            profile=profile,
            scores=scores,
            remaining_video_slots=remaining_video,
        )
        if animate:
            remaining_video -= 1
        visual = f"{project.prompt} — beat {index + 1}/{scene_count}"
        scenes.append(
            EngineSceneSpec(
                order_index=index,
                visual_prompt=visual,
                motion_prompt="subtle camera drift" if not animate else "motivated motion",
                narration=f"{project.prompt} beat {index + 1}.",
                duration_seconds=per_scene,
                production_class=klass,
                image_model=image_model,
                video_model=video_model,
                wants_video=animate,
                character_ids=char_ids,
            )
        )
        image_cost = reserve_image_usd(with_reference=needs_generated_ref or bool(char_ids))
        items.append(
            GenerationPlanItem(
                type=PlanItemType.STILL,
                model=image_model,
                quantity=1,
                estimated_provider_usd=image_cost,
                customer_stars=0,
                scene_id=str(index),
            )
        )
        if animate:
            video_cost = veo_cost(8)
            items.append(
                GenerationPlanItem(
                    type=PlanItemType.VIDEO,
                    model=video_model,
                    quantity=8,
                    estimated_provider_usd=video_cost,
                    customer_stars=0,
                    scene_id=str(index),
                )
            )
    items.append(
        GenerationPlanItem(
            type=PlanItemType.TTS,
            model=FIRST_CANARY_PROVIDERS["tts_model"],
            quantity=max(1, int(duration * 12)),
            estimated_provider_usd=reserve_tts_usd(),
            customer_stars=0,
        )
    )
    items.append(
        GenerationPlanItem(
            type=PlanItemType.MUSIC,
            model=FIRST_CANARY_PROVIDERS["music_model"],
            quantity=1,
            estimated_provider_usd=0.0,
            customer_stars=0,
        )
    )
    items.append(
        GenerationPlanItem(
            type=PlanItemType.RENDER,
            model=FIRST_CANARY_PROVIDERS["render_model"],
            quantity=1,
            estimated_provider_usd=0.0,
            customer_stars=0,
        )
    )
    estimated = round(sum(item.estimated_provider_usd for item in items), 4)
    for item in items:
        item.customer_stars = policy.stars_for_usd(item.estimated_provider_usd)
    return EngineProjectSpec(
        content_kind="custom_story",
        duration_seconds=duration,
        scene_count=scene_count,
        quality_profile=profile,
        aspect_ratio=project.aspect_ratio.value,
        language=project.language,
        characters=refs,
        scenes=tuple(scenes),
        frozen_items=tuple(items),
        estimated_provider_usd=estimated,
        hard_max_usd=hard_max_usd,
    )


def persist_engine_outline(
    repo: MemoryRepository,
    project: Project,
    spec: EngineProjectSpec,
    *,
    replace: bool = False,
) -> ScriptVersion:
    body_lines = [f"CUSTOM_STORY: {project.prompt}", "", f"Duration: {spec.duration_seconds:.0f}s"]
    for scene in spec.scenes:
        body_lines.append(f"Scene {scene.order_index + 1}: {scene.narration}")
    script = ScriptVersion(
        project_id=project.id,
        body="\n".join(body_lines),
        language=project.language,
    )
    repo.scripts[script.id] = script
    project.active_script_version_id = script.id
    existing = repo.scenes_for(project.id)
    if existing and not replace:
        return script
    if replace:
        for scene in existing:
            version_id = scene.active_version_id
            if version_id:
                repo.scene_versions.pop(version_id, None)
            repo.scenes.pop(scene.id, None)
    for spec_scene in spec.scenes:
        scene = Scene(project_id=project.id, order_index=spec_scene.order_index)
        version = SceneVersion(
            scene_id=scene.id,
            project_id=project.id,
            visual_prompt=spec_scene.visual_prompt,
            motion_prompt=spec_scene.motion_prompt,
            character_ids=list(spec_scene.character_ids),
            narration=spec_scene.narration,
            duration_seconds=spec_scene.duration_seconds,
            production_class=spec_scene.production_class.value,
            image_model=spec_scene.image_model,
            video_model=spec_scene.video_model,
        )
        scene.active_version_id = version.id
        repo.scenes[scene.id] = scene
        repo.scene_versions[version.id] = version
    return script


def freeze_plan(
    project: Project,
    spec: EngineProjectSpec,
    versions: list[SceneVersion],
) -> GenerationPlan:
    items = []
    for item in spec.frozen_items:
        scene_id = None
        if item.scene_id and item.scene_id.isdigit():
            index = int(item.scene_id)
            if 0 <= index < len(versions):
                scene_id = versions[index].scene_id
        items.append(item.model_copy(update={"scene_id": scene_id}))
    return assemble_plan(project, versions, items)


def frozen_plan_payload(plan: GenerationPlan, spec: EngineProjectSpec) -> dict:
    return {
        "plan_id": plan.id,
        "plan_hash": plan.plan_hash,
        "content_kind": spec.content_kind,
        "quality_profile": spec.quality_profile.value,
        "duration_seconds": spec.duration_seconds,
        "scene_count": spec.scene_count,
        "hard_max_usd": spec.hard_max_usd,
        "estimated_provider_usd": plan.estimated_provider_usd,
        "items": [
            {
                "type": item.type.value,
                "provider": FIRST_CANARY_PROVIDERS.get(
                    {
                        "script": "script",
                        "still": "image",
                        "video": "video",
                        "tts": "tts",
                        "music": "music",
                        "render": "render",
                    }.get(item.type.value, "script"),
                    "openai",
                ),
                "model": item.model,
                "quantity": item.quantity,
                "seconds": 8 if item.type is PlanItemType.VIDEO else None,
                "estimated_provider_usd": item.estimated_provider_usd,
                "reserved_provider_usd": item.estimated_provider_usd,
                "scene_id": item.scene_id,
            }
            for item in plan.items
        ],
        "providers": dict(FIRST_CANARY_PROVIDERS),
    }
