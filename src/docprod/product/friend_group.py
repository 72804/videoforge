from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

HOOK_FIRST_WRITER_INSTRUCTIONS = """
Write a short friend-group video people want to send to the people in it.
Reason explicitly about:
- first 1–3 second hook
- immediate curiosity or conflict
- recognizable friend personalities (use traits, quirks, catchphrases)
- escalation, reversals, callbacks
- payoff
- cliffhanger when it helps the next episode
Avoid generic AI-story exposition. Prefer spoken dialogue over narrator dump.
Do not write close-up lip-sync as a requirement; coverage can be reaction, OTS, or off-camera.
""".strip()


class DialogueLineSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    speaker_character_id: str
    text: str
    emotion: str = ""
    delivery: str = ""
    scene_id: str = ""


class SceneBeatSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene_id: str
    order_index: int = 0
    hook: str = ""
    visual: str = ""
    intent: str = ""
    character_ids: list[str] = Field(default_factory=list)
    duration_seconds: float = 6.0


class FriendGroupStorySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    logline: str = ""
    cold_open_hook: str
    premise: str
    final_story: str = ""
    target_duration: float = 0.0
    cast: list[str] = Field(default_factory=list)
    character_relationships: dict[str, str] = Field(default_factory=dict)
    character_relationship_context: dict[str, str] = Field(default_factory=dict)
    scene_beats: list[SceneBeatSpec] = Field(default_factory=list)
    dialogue_lines: list[DialogueLineSpec] = Field(default_factory=list)
    narration_lines: list[str] = Field(default_factory=list)
    comedy_drama_tension: str = ""
    callbacks: list[str] = Field(default_factory=list)
    payoff: str = ""
    ending: str = ""
    cliffhanger: str = ""
    continuity_updates: list[str] = Field(default_factory=list)
    motion_graphics_requests: list[str] = Field(default_factory=list)
    audio_intent: str = ""
    estimated_duration: float = 24.0
    content_style: str = "friend_group"
    writer_instructions: str = HOOK_FIRST_WRITER_INSTRUCTIONS
    engine_generated: bool = False
