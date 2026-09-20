from __future__ import annotations

import contextvars
import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")
user_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("user_id", default="")
project_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("project_id", default="")
job_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("job_id", default="")
scene_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("scene_id", default="")
attempt_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("attempt_id", default="")
provider_var: contextvars.ContextVar[str] = contextvars.ContextVar("provider", default="")
model_var: contextvars.ContextVar[str] = contextvars.ContextVar("model", default="")

_REDACT = frozenset(
    {
        "authorization",
        "init_data",
        "initdata",
        "session",
        "token",
        "api_key",
        "database_url",
        "password",
        "secret",
        "bot_token",
    }
)


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get() or "-"
        record.user_id = user_id_var.get() or "-"
        record.project_id = project_id_var.get() or "-"
        record.job_id = job_id_var.get() or "-"
        record.scene_id = scene_id_var.get() or "-"
        record.generation_attempt_id = attempt_id_var.get() or "-"
        record.provider = provider_var.get() or "-"
        record.model = model_var.get() or "-"
        return True


def new_request_id() -> str:
    return str(uuid.uuid4())


def bind_request_id(value: str | None) -> str:
    rid = (value or "").strip() or new_request_id()
    if len(rid) > 128 or any(ch in rid for ch in "\r\n"):
        rid = new_request_id()
    request_id_var.set(rid)
    return rid


@contextmanager
def log_scope(**fields: str) -> Iterator[None]:
    tokens = []
    mapping = {
        "user_id": user_id_var,
        "project_id": project_id_var,
        "job_id": job_id_var,
        "scene_id": scene_id_var,
        "attempt_id": attempt_id_var,
        "provider": provider_var,
        "model": model_var,
    }
    for key, value in fields.items():
        var = mapping.get(key)
        if var is None:
            continue
        tokens.append((var, var.set(value)))
    try:
        yield
    finally:
        for var, token in tokens:
            var.reset(token)


def safe_extra(payload: dict[str, object]) -> dict[str, object]:
    out = {}
    for key, value in payload.items():
        lowered = key.lower()
        if any(part in lowered for part in _REDACT):
            continue
        out[key] = value
    return out
