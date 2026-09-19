from __future__ import annotations

from dataclasses import dataclass

from docprod.exceptions import TtsInputLimitError

TTS_MAX_INPUT_CHARS = 4096
TTS_MAX_INPUT_TOKENS = 2000


def estimate_tts_tokens(text: str) -> int:
    """Closest local estimate without a live tokenizer dependency.

    Prefer tiktoken o200k_base when installed; otherwise Turkish ~3.2 chars/token.
    """
    compact = " ".join(text.split())
    if not compact:
        return 0
    try:
        import tiktoken

        encoder = tiktoken.get_encoding("o200k_base")
        return max(1, len(encoder.encode(compact)))
    except (ImportError, AttributeError, ValueError):
        return max(1, int(round(len(compact) / 3.2)))


@dataclass(frozen=True)
class TtsPreflight:
    character_count: int
    estimated_tokens: int
    max_chars: int = TTS_MAX_INPUT_CHARS
    max_tokens: int = TTS_MAX_INPUT_TOKENS
    within_limit: bool = True
    reason: str = ""


def inspect_tts_input(text: str) -> TtsPreflight:
    chars = len(text)
    tokens = estimate_tts_tokens(text)
    if chars > TTS_MAX_INPUT_CHARS:
        return TtsPreflight(
            character_count=chars,
            estimated_tokens=tokens,
            within_limit=False,
            reason=(
                f"Narration is {chars} characters; gpt-4o-mini-tts Speech API "
                f"input max is {TTS_MAX_INPUT_CHARS} characters."
            ),
        )
    if tokens > TTS_MAX_INPUT_TOKENS:
        return TtsPreflight(
            character_count=chars,
            estimated_tokens=tokens,
            within_limit=False,
            reason=(
                f"Estimated {tokens} input tokens exceeds gpt-4o-mini-tts "
                f"model limit of {TTS_MAX_INPUT_TOKENS}."
            ),
        )
    return TtsPreflight(character_count=chars, estimated_tokens=tokens)


def require_tts_within_limit(text: str) -> TtsPreflight:
    report = inspect_tts_input(text)
    if not report.within_limit:
        raise TtsInputLimitError(report.reason)
    return report
