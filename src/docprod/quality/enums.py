from __future__ import annotations

from enum import StrEnum


class SceneProductionClass(StrEnum):
    STATIC_CINEMATIC = "static_cinematic"
    SIMPLE_MOTION = "simple_motion"
    REACTION_SHOT = "reaction_shot"
    DIALOGUE_SHOT = "dialogue_shot"
    HERO_CINEMATIC = "hero_cinematic"
    PERFORMANCE_SHOT = "performance_shot"
    MUSIC_SYNCED_PERFORMANCE = "music_synced_performance"
    ESTABLISHING_SHOT = "establishing_shot"
    ARCHIVAL_SHOT = "archival_shot"
    TITLE_CARD = "title_card"
    TRANSITION_SHOT = "transition_shot"


class QualityProfile(StrEnum):
    ECONOMY = "economy"
    BALANCED = "balanced"
    PREMIUM = "premium"
    MAX_QUALITY = "max_quality"
    LOCAL_ONLY = "local_only"


class PriceMode(StrEnum):
    PER_REQUEST = "per_request"
    PER_SECOND = "per_second"
    PER_MINUTE = "per_minute"
    PER_CHARACTER = "per_character"
    PER_TOKEN = "per_token"
    PER_IMAGE = "per_image"
    UNKNOWN = "unknown"
    FREE = "free"


class CostConfidence(StrEnum):
    KNOWN = "known"
    ESTIMATED = "estimated"
    UNRESOLVED = "unresolved"


class ProviderStatus(StrEnum):
    CONFIGURED = "configured"
    UNCONFIGURED = "unconfigured"
    ONLINE = "online"
    OFFLINE = "offline"


class QualityTier(StrEnum):
    LOCAL = "local"
    ECONOMY = "economy"
    STANDARD = "standard"
    PREMIUM = "premium"
    MAX = "max"


class SfxClass(StrEnum):
    GENERIC_SFX = "generic_sfx"
    HERO_SFX = "hero_sfx"
    AMBIENCE = "ambience"
    FOLEY = "foley"
    TRANSITION_STING = "transition_sting"


class StoryFunction(StrEnum):
    HOOK = "hook"
    SETUP = "setup"
    ESCALATION = "escalation"
    REVEAL = "reveal"
    REVERSAL = "reversal"
    CONFRONTATION = "confrontation"
    PAYOFF = "payoff"
    CALLBACK = "callback"
    RESOLUTION = "resolution"
    COMEDIC_BEAT = "comedic_beat"
    TITLE = "title"
    BRIDGE = "bridge"


class RemoteJobState(StrEnum):
    REQUEST_SUBMITTED = "request_submitted"
    GENERATION_IN_PROGRESS = "generation_in_progress"
    GENERATION_SUCCEEDED_REMOTE = "generation_succeeded_remote"
    DOWNLOAD_FAILED = "download_failed"
    DOWNLOAD_SUCCEEDED = "download_succeeded"
    LOCAL_VALIDATION_SUCCEEDED = "local_validation_succeeded"
    CACHE_COMMITTED = "cache_committed"
    REMOTE_ARTIFACT_EXPIRED = "remote_artifact_expired"


class Modality(StrEnum):
    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"
    TTS = "tts"
    MUSIC = "music"
    SFX = "sfx"
    ALIGNMENT = "alignment"


class AdapterStatus(StrEnum):
    IMPLEMENTED = "implemented"
    CATALOG_ONLY = "catalog_only"
    DOCUMENTED_UNIMPLEMENTED = "documented_unimplemented"


class UpgradeKind(StrEnum):
    STILL_LOCAL_MOTION = "still_local_motion"
    SIMPLE_I2V = "simple_i2v"
    REACTION_I2V = "reaction_i2v"
    DIALOGUE_LIPSYNC = "dialogue_lipsync"
    IMPLIED_DIALOGUE_I2V = "implied_dialogue_i2v"
    HERO_CINEMATIC = "hero_cinematic"
    PERFORMANCE_TRANSFER = "performance_transfer"


class ReferenceMode(StrEnum):
    AUTO_GENERATED = "AUTO_GENERATED"
    CUSTOM = "CUSTOM"
    HYBRID = "HYBRID"
