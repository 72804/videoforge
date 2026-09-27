from __future__ import annotations

PRICING_VERSION = "2026-09-20"
VEO_LITE_720P_USD_PER_SEC = 0.05
LYRIA_35_USD_PER_SONG = 0.08
# Runway Dev: $0.01 per credit — https://docs.dev.runwayml.com/guides/pricing/
RUNWAY_CREDIT_USD = 0.01
RUNWAY_GEN45_CREDITS_PER_SEC = 12
RUNWAY_ACT_TWO_CREDITS_PER_SEC = 5
RUNWAY_GEN45_USD_PER_SEC = RUNWAY_CREDIT_USD * RUNWAY_GEN45_CREDITS_PER_SEC
RUNWAY_ACT_TWO_USD_PER_SEC = RUNWAY_CREDIT_USD * RUNWAY_ACT_TWO_CREDITS_PER_SEC
# ElevenLabs API — https://elevenlabs.io/pricing/api  (as of 2026-09-20)
ELEVEN_V3_USD_PER_1K_CHARS = 0.10
ELEVEN_SFX_USD_PER_MINUTE = 0.12
ELEVEN_MUSIC_USD_PER_MINUTE = 0.15
PRICING_AS_OF = "2026-09-20"
LYRIA_CLIP_USD_PER_30S = 0.04
LYRIA_REALTIME_USD = None  # PRICE UNRESOLVED
GEMINI_EMBEDDING_2_NOTE = "optional/cache-first; modality-based cost recorded if enabled"

HIGH_VALUE_VIDEO_UNITS = ("au_0005_0006", "au_0025")
LOW_VALUE_VIDEO_UNITS = ("au_0018", "au_0021_0022")
VEO_HARD_REQUESTS = 2
VEO_SECONDS_PER_REQUEST = 8
MUSIC_HARD_MAX = 4
LYRIA_IMAGE_LIMIT = 6
VEO_RETIME_RATIO_MAX = 1.07
MUSIC_DUCK_DB = -14.0
MUSIC_GAP_LIFT_DB = 6.0
TARGET_LUFS = -15.0
TRUE_PEAK_DBTP = -1.0


def veo_cost_usd(seconds: float) -> float:
    return round(seconds * VEO_LITE_720P_USD_PER_SEC, 4)


def lyria_cost_usd(songs: int) -> float:
    return round(songs * LYRIA_35_USD_PER_SONG, 4)


# Historical batch totals. Do not treat these as per-image list prices.
MAPLE_7_IMAGE_BATCH_TOTAL_USD = 0.06698  # entire 7-image Maple batch
BIRKO_DRAMA_IMAGE_PAID_CALLS = 24
BIRKO_DRAMA_IMAGE_ATTRIBUTABLE_USD = 0.371
# gpt-image-2.5-flare: usage-based $5 text-in / $8 image-in / $30 image-out per 1M tokens
OPENAI_IMAGE_TOKEN_RATES_NOTE = (
    "usage-based $5/$8/$30 per 1M tokens (text in / image in / image out); "
    "no per-image list price"
)
IMAGE_MIGRATION_HARD_CAP_USD = 1.00
# Conservative reserve per remaining paid still (includes extra image-in from refs).
IMAGE_MIGRATION_CONSERVATIVE_CALL_USD = 0.05
V2_VIDEO_VEO_USD = 3.20
V2_VIDEO_GEN45_USD = 0.00
V2_VIDEO_TOTAL_USD = 3.20
CUSTOM_STILL_MIGRATION_USD = 0.235525

# Official standard API text rates (story ensemble). Date is the day these
# list prices were registered in-repo; source is the provider standard API.
GPT6_ASTRA_INPUT_USD_PER_MILLION = 10.00
GPT6_ASTRA_OUTPUT_USD_PER_MILLION = 50.00
CLAUDE_OPUS_55_INPUT_USD_PER_MILLION = 4.00
CLAUDE_OPUS_55_OUTPUT_USD_PER_MILLION = 20.00
STORY_TEXT_PRICING_AS_OF = "2026-09-27"
GPT6_ASTRA_PRICING_SOURCE = (
    "OpenAI standard API list price for GPT-6 Astra: $10.00 / 1M input, "
    "$50.00 / 1M output"
)
CLAUDE_OPUS_55_PRICING_SOURCE = (
    "Anthropic standard API list price for Claude Opus 5.5: $4.00 / 1M input, "
    "$20.00 / 1M output"
)


def text_tokens_cost_usd(
    *,
    input_tokens: int,
    output_tokens: int,
    input_usd_per_million: float,
    output_usd_per_million: float,
) -> float:
    return round(
        (input_tokens / 1_000_000) * input_usd_per_million
        + (output_tokens / 1_000_000) * output_usd_per_million,
        6,
    )


def birko_implied_image_unit_usd() -> float:
    return round(BIRKO_DRAMA_IMAGE_ATTRIBUTABLE_USD / BIRKO_DRAMA_IMAGE_PAID_CALLS, 6)


def estimated_image_migration_usd(calls: int) -> float:
    """Observed Birko usage scaled by call count. Not a quote; refs add image-in tokens."""
    return round(birko_implied_image_unit_usd() * calls, 4)
