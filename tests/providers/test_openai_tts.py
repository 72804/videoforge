from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from docprod.config import Settings
from docprod.exceptions import PaidApiNotConfirmedError
from docprod.providers.openai_tts import OpenAITTSProvider
from docprod.providers.openai_whisper import OpenAIWhisperAligner


def _settings() -> Settings:
    return Settings(
        allow_paid_apis=True,
        openai_api_key=SecretStr("test-not-a-real-key"),
        log_level="INFO",
    )


def test_tts_requires_confirm_paid() -> None:
    provider = OpenAITTSProvider(settings=_settings(), client=SimpleNamespace())
    with pytest.raises(PaidApiNotConfirmedError):
        provider.synthesize("Merhaba", confirm_paid=False)
    assert provider.request_count == 0


def test_whisper_uses_word_timestamps(tmp_path) -> None:
    wav = tmp_path / "master.wav"
    wav.write_bytes(b"RIFF")
    calls: list[dict[str, object]] = []

    class FakeTranscriptions:
        def create(self, **kwargs: object) -> SimpleNamespace:
            calls.append(kwargs)
            return SimpleNamespace(
                model_dump=lambda: {
                    "language": "tr",
                    "words": [{"word": "Merhaba", "start": 0.0, "end": 0.4}],
                }
            )

    client = SimpleNamespace(audio=SimpleNamespace(transcriptions=FakeTranscriptions()))
    aligner = OpenAIWhisperAligner(settings=_settings(), client=client)
    words, language, payload = aligner.align_words(wav, confirm_paid=True, language="tr")
    assert language == "tr"
    assert words[0].word == "Merhaba"
    assert payload["words"][0]["word"] == "Merhaba"
    assert calls[0]["model"] == "whisper-1"
    assert calls[0]["response_format"] == "verbose_json"
    assert calls[0]["timestamp_granularities"] == ["word"]
    assert calls[0]["language"] == "tr"
    assert aligner.request_count == 1
