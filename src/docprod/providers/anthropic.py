from __future__ import annotations

from typing import Any

from docprod.config import Settings, get_settings, require_paid_call_allowed
from docprod.exceptions import DocumentedUnimplementedError, MissingApiKeyError

ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
CLAUDE_OPUS_55 = "claude-opus-5-5"


def require_anthropic_api_key(settings: Settings | None = None) -> str:
    cfg = settings or get_settings()
    if not cfg.anthropic_key_configured():
        raise MissingApiKeyError("Set ANTHROPIC_API_KEY on the worker. Not required for tests.")
    return cfg.anthropic_api_key.get_secret_value().strip()  # type: ignore[union-attr]


def build_messages_payload(
    *,
    model: str,
    messages: list[dict[str, str]],
    max_tokens: int = 4096,
    system: str = "",
    effort: str | None = None,
) -> dict[str, Any]:
    """Official Messages API body. Does not open a socket."""
    body: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if system:
        body["system"] = system
    if effort:
        body["output_config"] = {"effort": effort}
    return {
        "method": "POST",
        "url": ANTHROPIC_MESSAGES_URL,
        "headers": {
            "x-api-key": "${ANTHROPIC_API_KEY}",
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        },
        "json": body,
        "dry_run": True,
        "paid_calls": 0,
    }


class AnthropicMessagesAdapter:
    """Worker-only Messages API abstraction. Tests/development do not need the key."""

    def plan(
        self,
        *,
        model: str = CLAUDE_OPUS_55,
        messages: list[dict[str, str]] | None = None,
        max_tokens: int = 4096,
        system: str = "",
        effort: str | None = None,
    ) -> dict[str, Any]:
        return build_messages_payload(
            model=model,
            messages=messages or [{"role": "user", "content": "critique"}],
            max_tokens=max_tokens,
            system=system,
            effort=effort,
        )

    def generate(
        self,
        *,
        confirm_paid: bool,
        dry_run: bool = True,
        settings: Settings | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        planned = self.plan(**kwargs)
        if dry_run:
            return planned
        require_paid_call_allowed("anthropic", confirm_paid=confirm_paid, settings=settings)
        require_anthropic_api_key(settings)
        raise DocumentedUnimplementedError(
            CLAUDE_OPUS_55,
            "Anthropic Messages HTTP is not enabled this phase. Payload is documented only.",
        )
