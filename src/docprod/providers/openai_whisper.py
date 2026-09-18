from __future__ import annotations

from pathlib import Path
from typing import Any

from openai import OpenAI

from docprod.audio.models import WhisperWord
from docprod.config import Settings, get_settings, require_openai_api_key, require_paid_call_allowed


class OpenAIWhisperAligner:
    def __init__(self, *, settings: Settings | None = None, client: Any | None = None) -> None:
        self.settings = settings or get_settings()
        self._client = client
        self.request_count = 0

    def _client_or_create(self) -> Any:
        if self._client is not None:
            return self._client
        return OpenAI(api_key=require_openai_api_key(self.settings))

    def align_words(
        self,
        wav_path: Path,
        *,
        confirm_paid: bool,
        language: str = "tr",
    ) -> tuple[list[WhisperWord], str | None, dict[str, Any]]:
        require_paid_call_allowed("openai", confirm_paid=confirm_paid, settings=self.settings)
        require_openai_api_key(self.settings)
        client = self._client_or_create()
        self.request_count += 1
        with wav_path.open("rb") as handle:
            response = client.audio.transcriptions.create(
                model="whisper-1",
                file=handle,
                language=language,
                response_format="verbose_json",
                timestamp_granularities=["word"],
            )
        payload = response.model_dump() if hasattr(response, "model_dump") else dict(response)
        detected = payload.get("language")
        words: list[WhisperWord] = []
        for raw in payload.get("words") or []:
            if not isinstance(raw, dict):
                continue
            token = str(raw.get("word") or "").strip()
            if not token:
                continue
            words.append(
                WhisperWord(
                    word=token,
                    start=float(raw.get("start") or 0.0),
                    end=float(raw.get("end") or 0.0),
                )
            )
        return words, str(detected) if detected else language, payload
