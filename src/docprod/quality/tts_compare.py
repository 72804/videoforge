from __future__ import annotations

from docprod.config import Settings, get_settings
from docprod.providers.pricing import ELEVEN_V3_USD_PER_1K_CHARS
from docprod.quality.enums import CostConfidence
from docprod.quality.specs import TtsComparisonRow


def compare_narrators(
    *,
    character_count: int,
    speech_minutes: float,
    settings: Settings | None = None,
    cached_openai: bool = True,
) -> list[TtsComparisonRow]:
    cfg = settings or get_settings()
    eleven_cost = round((character_count / 1000.0) * ELEVEN_V3_USD_PER_1K_CHARS, 4)
    whisper = round(0.006 * speech_minutes, 4)
    return [
        TtsComparisonRow(
            model_id="gpt-4o-mini-tts",
            provider="openai",
            available=cfg.openai_key_configured(),
            estimated_cost=0.0 if cached_openai else None,
            cost_confidence=CostConfidence.KNOWN if cached_openai else CostConfidence.ESTIMATED,
            profile_usage="economy, balanced (reuse Cedar cache)",
            tags=["stability", "style_instruction", "turkish"],
            downstream=[] if cached_openai else ["re-align", "dialogue-sync-invalid"],
        ),
        TtsComparisonRow(
            model_id="eleven-v3",
            provider="elevenlabs",
            available=cfg.elevenlabs_key_configured(),
            estimated_cost=eleven_cost,
            cost_confidence=CostConfidence.KNOWN,
            profile_usage="premium, max_quality if narrator upgrade is explicit",
            tags=["expressiveness", "voice-cloning", "turkish"],
            downstream=["re-align", f"whisper~${whisper}", "dialogue-sync-invalid"],
        ),
        TtsComparisonRow(
            model_id="chatterbox-multilingual",
            provider="local",
            available=bool(cfg.local_tts_base_url.strip()),
            estimated_cost=0.0,
            cost_confidence=CostConfidence.KNOWN,
            profile_usage="local_only",
            tags=["local/free", "expressiveness", "turkish"],
            downstream=["re-align", "dialogue-sync-invalid"]
            if cfg.local_tts_base_url.strip()
            else ["missing LOCAL_TTS_BASE_URL"],
        ),
    ]
