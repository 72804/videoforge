from __future__ import annotations

from typing import Any

# Official unit rates as of this Phase 16B task. Not historical $0.02/$0.05/$0.03 lumps.
LUNA_INPUT_USD_PER_TOKEN = 0.20 / 1_000_000
LUNA_OUTPUT_USD_PER_TOKEN = 1.20 / 1_000_000
FLARE_TEXT_IN_USD_PER_TOKEN = 5.0 / 1_000_000
FLARE_IMAGE_IN_USD_PER_TOKEN = 8.0 / 1_000_000
FLARE_IMAGE_OUT_USD_PER_TOKEN = 30.0 / 1_000_000
TTS_TEXT_IN_USD_PER_TOKEN = 0.60 / 1_000_000
TTS_AUDIO_OUT_USD_PER_TOKEN = 12.0 / 1_000_000
VEO_LITE_720P_USD_PER_SEC = 0.05

CANARY_IMAGE_SIZE = "1024x1536"
CANARY_IMAGE_QUALITY = "medium"
CANARY_IMAGE_FORMAT = "jpeg"
# Published gpt-image medium 1024x1536 is about 1584 output tokens. Reserve higher.
CANARY_IMAGE_OUT_TOKENS_TYPICAL = 1584
CANARY_IMAGE_OUT_TOKENS_RESERVE = 2500
CANARY_IMAGE_TEXT_TOKENS_RESERVE = 2000
CANARY_IMAGE_IN_TOKENS_RESERVE = 2500
CANARY_SCRIPT_IN_TOKENS_RESERVE = 20_000
CANARY_SCRIPT_OUT_TOKENS_RESERVE = 8_000
CANARY_SCRIPT_IN_TOKENS_TYPICAL = 2_500
CANARY_SCRIPT_OUT_TOKENS_TYPICAL = 1_200
CANARY_TTS_TEXT_TOKENS_RESERVE = 2_000
CANARY_TTS_AUDIO_TOKENS_RESERVE = 40_000
CANARY_TTS_TEXT_TOKENS_TYPICAL = 400
CANARY_TTS_AUDIO_TOKENS_TYPICAL = 8_000
CANARY_VEO_SECONDS = 8
CANARY_VEO_RESOLUTION = "720p"
CHARACTER_REF_SCENE_ID = "character_ref"


def usd_round(value: float) -> float:
    return round(value, 6)


def script_cost(*, input_tokens: int, output_tokens: int) -> float:
    return usd_round(
        input_tokens * LUNA_INPUT_USD_PER_TOKEN + output_tokens * LUNA_OUTPUT_USD_PER_TOKEN
    )


def image_cost(
    *,
    text_tokens: int = 0,
    image_in_tokens: int = 0,
    image_out_tokens: int = 0,
) -> float:
    return usd_round(
        text_tokens * FLARE_TEXT_IN_USD_PER_TOKEN
        + image_in_tokens * FLARE_IMAGE_IN_USD_PER_TOKEN
        + image_out_tokens * FLARE_IMAGE_OUT_USD_PER_TOKEN
    )


def tts_cost(*, input_tokens: int = 0, audio_tokens: int = 0) -> float:
    return usd_round(
        input_tokens * TTS_TEXT_IN_USD_PER_TOKEN + audio_tokens * TTS_AUDIO_OUT_USD_PER_TOKEN
    )


def veo_cost(seconds: int = CANARY_VEO_SECONDS) -> float:
    return usd_round(seconds * VEO_LITE_720P_USD_PER_SEC)


def reserve_script_usd() -> float:
    return script_cost(
        input_tokens=CANARY_SCRIPT_IN_TOKENS_RESERVE,
        output_tokens=CANARY_SCRIPT_OUT_TOKENS_RESERVE,
    )


def typical_script_usd() -> float:
    return script_cost(
        input_tokens=CANARY_SCRIPT_IN_TOKENS_TYPICAL,
        output_tokens=CANARY_SCRIPT_OUT_TOKENS_TYPICAL,
    )


def reserve_image_usd(*, with_reference: bool) -> float:
    image_in = CANARY_IMAGE_IN_TOKENS_RESERVE if with_reference else 0
    return image_cost(
        text_tokens=CANARY_IMAGE_TEXT_TOKENS_RESERVE,
        image_in_tokens=image_in,
        image_out_tokens=CANARY_IMAGE_OUT_TOKENS_RESERVE,
    )


def typical_image_usd(*, with_reference: bool) -> float:
    image_in = 1200 if with_reference else 0
    return image_cost(
        text_tokens=600,
        image_in_tokens=image_in,
        image_out_tokens=CANARY_IMAGE_OUT_TOKENS_TYPICAL,
    )


def reserve_tts_usd() -> float:
    return tts_cost(
        input_tokens=CANARY_TTS_TEXT_TOKENS_RESERVE,
        audio_tokens=CANARY_TTS_AUDIO_TOKENS_RESERVE,
    )


def typical_tts_usd() -> float:
    return tts_cost(
        input_tokens=CANARY_TTS_TEXT_TOKENS_TYPICAL,
        audio_tokens=CANARY_TTS_AUDIO_TOKENS_TYPICAL,
    )


def image_cost_from_usage(usage: dict[str, Any] | None) -> float | None:
    if not usage:
        return None
    text_in = usage.get("input_tokens") or usage.get("text_tokens")
    image_out = usage.get("output_tokens")
    image_in = 0
    details = usage.get("input_tokens_details")
    if isinstance(details, dict):
        image_in = int(details.get("image_tokens") or 0)
        if details.get("text_tokens") is not None:
            text_in = details.get("text_tokens")
    if text_in is None and image_out is None:
        return None
    return image_cost(
        text_tokens=int(text_in or 0),
        image_in_tokens=int(image_in or 0),
        image_out_tokens=int(image_out or 0),
    )


def text_cost_from_usage(usage: dict[str, Any] | None) -> float | None:
    if not usage:
        return None
    input_tokens = usage.get("input_tokens") or usage.get("prompt_tokens")
    output_tokens = usage.get("output_tokens") or usage.get("completion_tokens")
    if input_tokens is None and output_tokens is None:
        return None
    return script_cost(input_tokens=int(input_tokens or 0), output_tokens=int(output_tokens or 0))


def tts_cost_from_usage(usage: dict[str, Any] | None) -> float | None:
    if not usage:
        return None
    text_in = usage.get("input_tokens") or usage.get("prompt_tokens")
    audio_out = usage.get("output_tokens") or usage.get("completion_tokens")
    if text_in is None and audio_out is None:
        return None
    return tts_cost(input_tokens=int(text_in or 0), audio_tokens=int(audio_out or 0))


def estimate_text_tokens(text: str) -> int:
    words = [part for part in text.split() if part]
    return max(1, int(len(words) * 1.3) + 8)
