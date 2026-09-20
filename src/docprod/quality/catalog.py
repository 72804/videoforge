from __future__ import annotations

from functools import lru_cache

from docprod.providers.pricing import LYRIA_35_USD_PER_SONG, VEO_LITE_720P_USD_PER_SEC
from docprod.quality.enums import CostConfidence, Modality, PriceMode, QualityTier
from docprod.quality.specs import ModelSpec, PricingSpec

KNOWN_TTS_TEXT = PricingSpec(
    mode=PriceMode.PER_TOKEN,
    value=0.60 / 1_000_000,
    unit="text_token_in",
    notes="$0.60/1M text in; audio-out $12/1M when usage present",
    confidence=CostConfidence.KNOWN,
)
KNOWN_WHISPER = PricingSpec(
    mode=PriceMode.PER_MINUTE,
    value=0.006,
    unit="minute",
    notes="OpenAI Whisper $0.006/min",
    confidence=CostConfidence.KNOWN,
)
KNOWN_VEO_LITE = PricingSpec(
    mode=PriceMode.PER_SECOND,
    value=VEO_LITE_720P_USD_PER_SEC,
    unit="second",
    notes="Veo 3.1 Lite 720p known unit price",
    confidence=CostConfidence.KNOWN,
)
KNOWN_LYRIA = PricingSpec(
    mode=PriceMode.PER_REQUEST,
    value=LYRIA_35_USD_PER_SONG,
    unit="song",
    notes="Lyria Interactions $0.08/song",
    confidence=CostConfidence.KNOWN,
)
FREE = PricingSpec(mode=PriceMode.FREE, value=0.0, unit="call", confidence=CostConfidence.KNOWN)
UNKNOWN = PricingSpec(mode=PriceMode.UNKNOWN, confidence=CostConfidence.UNRESOLVED)


def _m(
    model_id: str,
    provider: str,
    modality: Modality,
    *,
    caps: tuple[str, ...] = (),
    tier: QualityTier = QualityTier.STANDARD,
    speed: str = "unknown",
    pricing: PricingSpec | None = None,
    implemented: bool = False,
    async_remote: bool = False,
    local: bool = False,
    notes: str = "",
    display: str = "",
) -> ModelSpec:
    return ModelSpec(
        model_id=model_id,
        provider=provider,
        modality=modality,
        display_name=display or model_id,
        capabilities=caps,
        quality_tier=tier,
        speed_tier=speed,
        pricing=pricing or UNKNOWN,
        implemented=implemented,
        async_remote=async_remote,
        local=local,
        notes=notes,
    )


def _build_catalog() -> tuple[ModelSpec, ...]:
    text = (
        "story_generation",
        "script_doctor",
        "scene_planning",
        "classification",
        "critique",
        "long_context",
    )
    return (
        _m(
            "gpt-5.6-sol",
            "openai",
            Modality.TEXT,
            caps=text,
            tier=QualityTier.PREMIUM,
            notes="Optional higher-tier OpenAI slot",
        ),
        _m(
            "gpt-5.6-terra",
            "openai",
            Modality.TEXT,
            caps=text,
            implemented=True,
            notes="Current writer default in Settings.writer_model",
        ),
        _m(
            "gpt-5.6-luna",
            "openai",
            Modality.TEXT,
            caps=text,
            implemented=True,
            notes="Research/dossier/planner default",
        ),
        _m("claude-sonnet", "anthropic", Modality.TEXT, caps=text, notes="Provider slot"),
        _m("gemini-pro", "google", Modality.TEXT, caps=text, notes="Provider slot"),
        _m(
            "qwen-local",
            "local",
            Modality.TEXT,
            caps=text,
            tier=QualityTier.LOCAL,
            local=True,
            pricing=FREE,
            notes="OpenAI-compatible LOCAL_LLM_BASE_URL",
        ),
        _m(
            "gpt-image-2.5-sunburst",
            "openai",
            Modality.IMAGE,
            caps=(
                "text_to_image",
                "image_reference",
                "multi_reference",
                "character_consistency",
                "editing",
                "high_fidelity_character",
            ),
            tier=QualityTier.PREMIUM,
            notes="Preferred for character refs when configured; list price UNRESOLVED",
        ),
        _m(
            "gpt-image-2.5-flare",
            "openai",
            Modality.IMAGE,
            caps=(
                "text_to_image",
                "image_reference",
                "multi_reference",
                "character_consistency",
                "editing",
                "fast_generation",
            ),
            implemented=True,
            notes="Current default timeline stills; usage-based $5/$8/$30 per 1M",
            pricing=PricingSpec(
                mode=PriceMode.PER_TOKEN,
                notes="usage-based; per-image list price UNRESOLVED",
                confidence=CostConfidence.ESTIMATED,
            ),
        ),
        _m(
            "gemini-nano-banana",
            "google",
            Modality.IMAGE,
            caps=("text_to_image", "image_reference"),
            notes="Gemini/Nano Banana image slot",
        ),
        _m(
            "higgsfield-soul",
            "higgsfield",
            Modality.IMAGE,
            caps=("text_to_image", "character_consistency", "high_fidelity_character"),
            tier=QualityTier.PREMIUM,
            notes="Soul / Soul ID slot",
        ),
        _m(
            "comfyui-local",
            "local",
            Modality.IMAGE,
            caps=("text_to_image", "image_reference", "editing"),
            tier=QualityTier.LOCAL,
            local=True,
            pricing=FREE,
            notes="LOCAL_IMAGE_BASE_URL",
        ),
        _m(
            "veo-3.1-lite-generate-preview",
            "google",
            Modality.VIDEO,
            caps=("image_to_video", "native_audio"),
            implemented=True,
            async_remote=True,
            pricing=KNOWN_VEO_LITE,
            speed="fast",
            notes="Implemented Veo 3.1 Lite I2V 8s 720p",
        ),
        _m(
            "veo-3.1-fast",
            "google",
            Modality.VIDEO,
            caps=("image_to_video", "text_to_video"),
            speed="fast",
            notes="Catalog only; HTTP contract not implemented here",
        ),
        _m(
            "veo-3.1-standard",
            "google",
            Modality.VIDEO,
            caps=("image_to_video", "text_to_video", "native_audio"),
            tier=QualityTier.PREMIUM,
            notes="Catalog only; price UNRESOLVED",
        ),
        _m(
            "kling-3",
            "higgsfield",
            Modality.VIDEO,
            caps=("image_to_video", "text_to_video"),
            notes="UNIMPLEMENTED adapter boundary",
        ),
        _m(
            "seedance",
            "higgsfield",
            Modality.VIDEO,
            caps=("image_to_video",),
            notes="UNIMPLEMENTED adapter boundary",
        ),
        _m(
            "wan",
            "higgsfield",
            Modality.VIDEO,
            caps=("image_to_video", "text_to_video"),
            notes="Hosted Wan family slot",
        ),
        _m(
            "minimax-hailuo",
            "higgsfield",
            Modality.VIDEO,
            caps=("image_to_video",),
            notes="MiniMax/Hailuo slot",
        ),
        _m(
            "runway-gen-4.5",
            "runway",
            Modality.VIDEO,
            caps=("image_to_video", "text_to_video", "camera_control"),
            tier=QualityTier.PREMIUM,
            notes="UNIMPLEMENTED",
        ),
        _m(
            "runway-act-two",
            "runway",
            Modality.VIDEO,
            caps=("performance_transfer", "driving_video", "lip_sync"),
            tier=QualityTier.PREMIUM,
            notes="UNIMPLEMENTED performance transfer",
        ),
        _m(
            "higgsfield-genjutsu",
            "higgsfield",
            Modality.VIDEO,
            caps=("performance_transfer", "driving_video"),
            tier=QualityTier.PREMIUM,
            notes="Genjutsu motion transfer slot",
        ),
        _m(
            "ltx-local",
            "local",
            Modality.VIDEO,
            caps=("image_to_video", "text_to_video"),
            local=True,
            pricing=FREE,
            tier=QualityTier.LOCAL,
        ),
        _m(
            "hunyuan-video-local",
            "local",
            Modality.VIDEO,
            caps=("text_to_video", "image_to_video"),
            local=True,
            pricing=FREE,
            tier=QualityTier.LOCAL,
        ),
        _m(
            "hunyuan-avatar-local",
            "local",
            Modality.VIDEO,
            caps=("lip_sync", "dialogue", "driving_video"),
            local=True,
            pricing=FREE,
            tier=QualityTier.LOCAL,
        ),
        _m(
            "wan-local",
            "local",
            Modality.VIDEO,
            caps=("image_to_video", "text_to_video"),
            local=True,
            pricing=FREE,
            tier=QualityTier.LOCAL,
        ),
        _m(
            "eleven-v3",
            "elevenlabs",
            Modality.TTS,
            caps=("turkish", "expressiveness", "voice_cloning", "style_instruction"),
            tier=QualityTier.PREMIUM,
        ),
        _m(
            "eleven-multilingual",
            "elevenlabs",
            Modality.TTS,
            caps=("turkish", "long_form"),
        ),
        _m(
            "gpt-4o-mini-tts",
            "openai",
            Modality.TTS,
            caps=("turkish", "style_instruction", "long_form"),
            implemented=True,
            pricing=KNOWN_TTS_TEXT,
        ),
        _m("gemini-tts", "google", Modality.TTS, caps=("turkish",)),
        _m(
            "chatterbox-multilingual",
            "local",
            Modality.TTS,
            caps=("turkish", "local", "expressiveness"),
            local=True,
            pricing=FREE,
            tier=QualityTier.LOCAL,
        ),
        _m(
            "lyria-3.5",
            "google",
            Modality.MUSIC,
            caps=("instrumental", "image_conditioning"),
            implemented=True,
            pricing=KNOWN_LYRIA,
        ),
        _m(
            "eleven-music",
            "elevenlabs",
            Modality.MUSIC,
            caps=("instrumental", "lyrics", "section_control", "inpainting"),
            tier=QualityTier.PREMIUM,
        ),
        _m(
            "stable-audio",
            "stability",
            Modality.MUSIC,
            caps=("instrumental", "duration_control"),
        ),
        _m(
            "ace-step-local",
            "local",
            Modality.MUSIC,
            caps=("instrumental", "local"),
            local=True,
            pricing=FREE,
            tier=QualityTier.LOCAL,
        ),
        _m(
            "yue-local",
            "local",
            Modality.MUSIC,
            caps=("instrumental", "lyrics", "local"),
            local=True,
            pricing=FREE,
            tier=QualityTier.LOCAL,
        ),
        _m(
            "local-library",
            "local",
            Modality.SFX,
            caps=("generic",),
            implemented=True,
            local=True,
            pricing=FREE,
            tier=QualityTier.LOCAL,
        ),
        _m(
            "procedural-sfx",
            "local",
            Modality.SFX,
            caps=("generic", "foley"),
            implemented=True,
            local=True,
            pricing=FREE,
            tier=QualityTier.LOCAL,
        ),
        _m("eleven-sfx", "elevenlabs", Modality.SFX, caps=("hero",), tier=QualityTier.PREMIUM),
        _m("stable-audio-sfx", "stability", Modality.SFX, caps=("hero", "ambience")),
        _m(
            "audioldm2-local",
            "local",
            Modality.SFX,
            caps=("generic", "local"),
            local=True,
            pricing=FREE,
            tier=QualityTier.LOCAL,
        ),
        _m(
            "whisper-1",
            "openai",
            Modality.ALIGNMENT,
            caps=("word_timestamps", "language_support"),
            implemented=True,
            pricing=KNOWN_WHISPER,
        ),
        _m(
            "openai-transcription",
            "openai",
            Modality.ALIGNMENT,
            caps=("word_timestamps",),
            notes="Newer transcription interface slot",
        ),
        _m(
            "eleven-scribe",
            "elevenlabs",
            Modality.ALIGNMENT,
            caps=("word_timestamps", "speaker_diarization"),
        ),
        _m(
            "faster-whisper-local",
            "local",
            Modality.ALIGNMENT,
            caps=("word_timestamps", "local", "language_support"),
            local=True,
            pricing=FREE,
            implemented=False,
            tier=QualityTier.LOCAL,
        ),
    )


@lru_cache
def model_catalog() -> tuple[ModelSpec, ...]:
    return _build_catalog()


def models_by_id() -> dict[str, ModelSpec]:
    return {item.model_id: item for item in model_catalog()}


def models_for(modality: Modality) -> list[ModelSpec]:
    return [item for item in model_catalog() if item.modality is modality]


def get_model(model_id: str) -> ModelSpec | None:
    return models_by_id().get(model_id)
