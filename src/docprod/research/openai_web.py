from __future__ import annotations

import time
from typing import Any

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    OpenAI,
    RateLimitError,
)

from docprod.config import Settings, get_settings, require_openai_api_key, require_paid_call_allowed
from docprod.providers.request_budget import ModelRequestBudget
from docprod.research.models import MAX_WEB_TOOL_CALLS, ApiUsage

SECRET_KEYS = {
    "authorization",
    "api_key",
    "api-key",
    "cookie",
    "set-cookie",
    "x-api-key",
    "token",
    "secret",
    "openai-api-key",
}


def sanitize_payload(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            if str(key).lower() in SECRET_KEYS:
                continue
            cleaned[str(key)] = sanitize_payload(item)
        return cleaned
    if isinstance(value, list):
        return [sanitize_payload(item) for item in value]
    if isinstance(value, str) and len(value) > 20000:
        return value[:20000] + "…"
    return value


def dump_response(response: Any) -> dict[str, Any]:
    dump = getattr(response, "model_dump", None)
    if callable(dump):
        payload = dump()
        if isinstance(payload, dict):
            return sanitize_payload(payload)
    if isinstance(response, dict):
        return sanitize_payload(response)
    return {"repr": sanitize_payload(str(response))}


def extract_output_text(response: Any, payload: dict[str, Any]) -> str:
    text = getattr(response, "output_text", None)
    if isinstance(text, str) and text.strip():
        return text
    chunks: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") in {"output_text", "text"} and isinstance(node.get("text"), str):
                chunks.append(node["text"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload.get("output") or payload)
    return "".join(chunks)


def extract_usage(
    response: Any, *, model: str, web_search_calls: int, elapsed: float, request_count: int
) -> ApiUsage:
    usage = getattr(response, "usage", None)
    payload: dict[str, Any] = {}
    if usage is not None and hasattr(usage, "model_dump"):
        dumped = usage.model_dump()
        if isinstance(dumped, dict):
            payload = dumped
    elif isinstance(usage, dict):
        payload = usage
    input_details = payload.get("input_tokens_details") or payload.get("input_details") or {}
    output_details = payload.get("output_tokens_details") or payload.get("output_details") or {}
    extra: dict[str, int | float | str] = {}
    for key, value in payload.items():
        if isinstance(value, (int, float, str)) and key not in {
            "input_tokens",
            "output_tokens",
        }:
            extra[str(key)] = value
    return ApiUsage(
        model=model,
        input_tokens=_as_int(payload.get("input_tokens")),
        output_tokens=_as_int(payload.get("output_tokens")),
        cached_tokens=_as_int(
            input_details.get("cached_tokens") if isinstance(input_details, dict) else None
        ),
        reasoning_tokens=_as_int(
            output_details.get("reasoning_tokens") if isinstance(output_details, dict) else None
        ),
        web_search_call_count=web_search_calls,
        duration_seconds=round(elapsed, 3),
        request_count=request_count,
        extra=extra,
    )


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def count_web_search_calls(payload: dict[str, Any]) -> int:
    count = 0

    def walk(node: Any) -> None:
        nonlocal count
        if isinstance(node, dict):
            if str(node.get("type") or "") == "web_search_call":
                count += 1
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload.get("output") or payload)
    return count


def _is_transient(exc: BaseException) -> bool:
    if isinstance(exc, APIConnectionError | APITimeoutError | RateLimitError):
        return True
    if isinstance(exc, APIStatusError) and exc.status_code in {429, 500, 502, 503, 504}:
        return True
    return False


class OpenAIResponsesProvider:
    def __init__(self, *, settings: Settings | None = None, client: Any | None = None) -> None:
        self.settings = settings or get_settings()
        self._client = client
        self.request_count = 0

    def _client_or_create(self) -> Any:
        if self._client is not None:
            return self._client
        return OpenAI(api_key=require_openai_api_key(self.settings))

    def create(
        self,
        *,
        model: str,
        instructions: str,
        input_text: str,
        confirm_paid: bool,
        tools: list[dict[str, Any]] | None = None,
        include: list[str] | None = None,
        max_tool_calls: int | None = None,
        text_format: dict[str, Any] | None = None,
        budget: ModelRequestBudget | None = None,
        stage: str = "responses",
        allow_retry: bool = True,
    ) -> Any:
        require_paid_call_allowed("openai", confirm_paid=confirm_paid, settings=self.settings)
        require_openai_api_key(self.settings)
        client = self._client_or_create()
        kwargs: dict[str, Any] = {
            "model": model,
            "instructions": instructions,
            "input": input_text,
        }
        if tools:
            kwargs["tools"] = tools
        if include:
            kwargs["include"] = include
        if max_tool_calls is not None:
            kwargs["max_tool_calls"] = max_tool_calls
        if text_format is not None:
            kwargs["text"] = text_format
        last_error: BaseException | None = None
        attempts = 2 if allow_retry else 1
        for attempt in range(attempts):
            if budget is not None:
                budget.reserve(stage)
            try:
                self.request_count += 1
                responses = getattr(client, "responses")
                return responses.create(**kwargs)
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt + 1 < attempts and _is_transient(exc):
                    time.sleep(0.4)
                    continue
                raise
        raise RuntimeError(f"Responses API failed: {last_error}")


def web_search_tools() -> list[dict[str, str]]:
    return [{"type": "web_search"}]


def web_search_include() -> list[str]:
    return ["web_search_call.action.sources"]


def default_max_tool_calls() -> int:
    return MAX_WEB_TOOL_CALLS
