from __future__ import annotations

PRICING_VERSION = "2026-09-19"
VEO_LITE_720P_USD_PER_SEC = 0.05
LYRIA_35_USD_PER_SONG = 0.08
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
