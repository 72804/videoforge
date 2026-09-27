from __future__ import annotations

from docprod.quality.catalog import get_model
from docprod.quality.enums import NativeAudioPolicy


def native_audio_use(model_id: str, *, needs_character_dialogue: bool) -> str:
    """Native video audio may be kept as ambience; never replaces VoiceProfile dialogue."""
    spec = get_model(model_id)
    policy = spec.native_audio_policy if spec else NativeAudioPolicy.NONE
    if policy is NativeAudioPolicy.NONE or not spec or not spec.native_audio:
        return "discard_or_none"
    if needs_character_dialogue:
        return "replace_or_mix_under_dialogue"
    if policy is NativeAudioPolicy.AMBIENT_OPTIONAL:
        return "keep_ambient_optional"
    return "replace_or_mix_under_dialogue"
