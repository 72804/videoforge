from __future__ import annotations

from dataclasses import dataclass

from docprod.quality.enums import QualityProfile, QualityTier

VIDEO_SECONDS = 8.0


@dataclass(frozen=True)
class ProfilePolicy:
    profile: QualityProfile
    max_paid_usd: float
    target_paid_usd: float
    motion_video_threshold: float
    allow_paid: bool
    script_model: str
    critic_model: str
    character_image_model: str
    timeline_image_model: str
    simple_motion_model: str
    reaction_model: str
    hero_model: str
    dialogue_model: str
    performance_model: str
    music_model: str
    sfx_model: str
    tts_model: str
    alignment_model: str
    premium_sfx: bool
    default_tier: QualityTier


POLICIES: dict[QualityProfile, ProfilePolicy] = {
    QualityProfile.ECONOMY: ProfilePolicy(
        profile=QualityProfile.ECONOMY,
        max_paid_usd=0.25,
        target_paid_usd=0.0,
        motion_video_threshold=0.92,
        allow_paid=True,
        script_model="gpt-5.6-luna",
        critic_model="local-heuristic",
        character_image_model="gpt-image-2.5-flare",
        timeline_image_model="gpt-image-2.5-flare",
        simple_motion_model="local-camera",
        reaction_model="local-camera",
        hero_model="local-camera",
        dialogue_model="narration-over-image",
        performance_model="local-camera",
        music_model="lyria-3.5",
        sfx_model="procedural-sfx",
        tts_model="gpt-4o-mini-tts",
        alignment_model="whisper-1",
        premium_sfx=False,
        default_tier=QualityTier.ECONOMY,
    ),
    QualityProfile.BALANCED: ProfilePolicy(
        profile=QualityProfile.BALANCED,
        max_paid_usd=5.0,
        target_paid_usd=3.2,
        motion_video_threshold=0.60,
        allow_paid=True,
        script_model="gpt-5.6-terra",
        critic_model="local-heuristic",
        character_image_model="gpt-image-2.5-sunburst",
        timeline_image_model="gpt-image-2.5-flare",
        simple_motion_model="veo-3.1-lite-generate-preview",
        reaction_model="veo-3.1-lite-generate-preview",
        hero_model="veo-3.1-lite-generate-preview",
        dialogue_model="veo-3.1-lite-generate-preview",
        performance_model="veo-3.1-lite-generate-preview",
        music_model="lyria-3.5",
        sfx_model="procedural-sfx",
        tts_model="gpt-4o-mini-tts",
        alignment_model="whisper-1",
        premium_sfx=False,
        default_tier=QualityTier.STANDARD,
    ),
    QualityProfile.PREMIUM: ProfilePolicy(
        profile=QualityProfile.PREMIUM,
        max_paid_usd=18.0,
        target_paid_usd=12.0,
        motion_video_threshold=0.45,
        allow_paid=True,
        script_model="gpt-5.6-sol",
        critic_model="gpt-5.6-luna",
        character_image_model="gpt-image-2.5-sunburst",
        timeline_image_model="gpt-image-2.5-flare",
        simple_motion_model="veo-3.1-lite-generate-preview",
        reaction_model="veo-3.1-lite-generate-preview",
        hero_model="veo-3.1-standard",
        dialogue_model="runway-act-two",
        performance_model="higgsfield-genjutsu",
        music_model="eleven-music",
        sfx_model="eleven-sfx",
        tts_model="eleven-v3",
        alignment_model="whisper-1",
        premium_sfx=True,
        default_tier=QualityTier.PREMIUM,
    ),
    QualityProfile.MAX_QUALITY: ProfilePolicy(
        profile=QualityProfile.MAX_QUALITY,
        max_paid_usd=40.0,
        target_paid_usd=22.0,
        motion_video_threshold=0.35,
        allow_paid=True,
        script_model="gpt-5.6-sol",
        critic_model="gpt-5.6-luna",
        character_image_model="gpt-image-2.5-sunburst",
        timeline_image_model="gpt-image-2.5-sunburst",
        simple_motion_model="veo-3.1-standard",
        reaction_model="veo-3.1-standard",
        hero_model="runway-gen-4.5",
        dialogue_model="runway-act-two",
        performance_model="runway-act-two",
        music_model="eleven-music",
        sfx_model="eleven-sfx",
        tts_model="eleven-v3",
        alignment_model="eleven-scribe",
        premium_sfx=True,
        default_tier=QualityTier.MAX,
    ),
    QualityProfile.LOCAL_ONLY: ProfilePolicy(
        profile=QualityProfile.LOCAL_ONLY,
        max_paid_usd=0.0,
        target_paid_usd=0.0,
        motion_video_threshold=0.70,
        allow_paid=False,
        script_model="qwen-local",
        critic_model="local-heuristic",
        character_image_model="comfyui-local",
        timeline_image_model="comfyui-local",
        simple_motion_model="ltx-local",
        reaction_model="ltx-local",
        hero_model="hunyuan-video-local",
        dialogue_model="hunyuan-avatar-local",
        performance_model="hunyuan-avatar-local",
        music_model="ace-step-local",
        sfx_model="audioldm2-local",
        tts_model="chatterbox-multilingual",
        alignment_model="faster-whisper-local",
        premium_sfx=False,
        default_tier=QualityTier.LOCAL,
    ),
}


def policy_for(profile: QualityProfile) -> ProfilePolicy:
    return POLICIES[profile]
