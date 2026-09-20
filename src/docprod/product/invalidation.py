from __future__ import annotations

from enum import StrEnum


class InvalidationEvent(StrEnum):
    CHARACTER_REFERENCE_CHANGED = "character_reference_changed"
    SCENE_VISUAL_PROMPT_CHANGED = "scene_visual_prompt_changed"
    SCENE_MOTION_PROMPT_CHANGED = "scene_motion_prompt_changed"
    SCENE_VIDEO_MODEL_CHANGED = "scene_video_model_changed"
    SCENE_IMAGE_MODEL_CHANGED = "scene_image_model_changed"
    SCENE_CHARACTERS_CHANGED = "scene_characters_changed"
    SCENE_DURATION_CHANGED = "scene_duration_changed"
    SCENE_REORDERED = "scene_reordered"
    SCENE_DELETED = "scene_deleted"
    SCENE_IMAGE_REPLACED = "scene_image_replaced"
    SCENE_VIDEO_REPLACED = "scene_video_replaced"


def effects_for(event: InvalidationEvent) -> dict[str, bool]:
    """Deterministic stale flags. True means that artifact becomes stale."""
    image = event in {
        InvalidationEvent.CHARACTER_REFERENCE_CHANGED,
        InvalidationEvent.SCENE_VISUAL_PROMPT_CHANGED,
        InvalidationEvent.SCENE_IMAGE_MODEL_CHANGED,
        InvalidationEvent.SCENE_CHARACTERS_CHANGED,
        InvalidationEvent.SCENE_IMAGE_REPLACED,
    }
    video = event in {
        InvalidationEvent.CHARACTER_REFERENCE_CHANGED,
        InvalidationEvent.SCENE_VISUAL_PROMPT_CHANGED,
        InvalidationEvent.SCENE_MOTION_PROMPT_CHANGED,
        InvalidationEvent.SCENE_VIDEO_MODEL_CHANGED,
        InvalidationEvent.SCENE_CHARACTERS_CHANGED,
        InvalidationEvent.SCENE_DURATION_CHANGED,
        InvalidationEvent.SCENE_IMAGE_REPLACED,
        InvalidationEvent.SCENE_VIDEO_REPLACED,
    }
    render = event in {
        InvalidationEvent.CHARACTER_REFERENCE_CHANGED,
        InvalidationEvent.SCENE_VISUAL_PROMPT_CHANGED,
        InvalidationEvent.SCENE_MOTION_PROMPT_CHANGED,
        InvalidationEvent.SCENE_VIDEO_MODEL_CHANGED,
        InvalidationEvent.SCENE_IMAGE_MODEL_CHANGED,
        InvalidationEvent.SCENE_CHARACTERS_CHANGED,
        InvalidationEvent.SCENE_DURATION_CHANGED,
        InvalidationEvent.SCENE_REORDERED,
        InvalidationEvent.SCENE_DELETED,
        InvalidationEvent.SCENE_IMAGE_REPLACED,
        InvalidationEvent.SCENE_VIDEO_REPLACED,
    }
    if event is InvalidationEvent.SCENE_MOTION_PROMPT_CHANGED:
        image = False
    if event is InvalidationEvent.SCENE_VIDEO_MODEL_CHANGED:
        image = False
    if event is InvalidationEvent.SCENE_REORDERED:
        image = False
        video = False
    if event is InvalidationEvent.SCENE_IMAGE_REPLACED:
        image = False
    if event is InvalidationEvent.SCENE_VIDEO_REPLACED:
        image = False
        video = False
    return {"image": image, "video": video, "render": render}
