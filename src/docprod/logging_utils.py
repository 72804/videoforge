from __future__ import annotations

import logging

from docprod.config import Settings
from docprod.observability import ContextFilter

_LOGGER_NAME = "docprod"
_VALID_LEVELS = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"}


class InvalidLogLevelError(ValueError):
    """Raised when LOG_LEVEL is not a standard logging level name."""


def resolve_log_level(level_name: str) -> int:
    normalized = level_name.strip().upper()
    if normalized not in _VALID_LEVELS:
        raise InvalidLogLevelError(
            f"Invalid log level {level_name!r}. "
            f"Expected one of: {', '.join(sorted(_VALID_LEVELS))}"
        )
    return int(getattr(logging, normalized))


def configure_logging(settings: Settings) -> logging.Logger:
    """Configure the package logger. Safe to call repeatedly."""
    level = resolve_log_level(settings.log_level)
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(level)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s %(name)s request_id=%(request_id)s "
                "user_id=%(user_id)s project_id=%(project_id)s job_id=%(job_id)s "
                "scene_id=%(scene_id)s generation_attempt_id=%(generation_attempt_id)s "
                "provider=%(provider)s model=%(model)s: %(message)s"
            )
        )
        handler.addFilter(ContextFilter())
        logger.addHandler(handler)
    filt = ContextFilter()
    for handler in logger.handlers:
        handler.setLevel(level)
        if not any(isinstance(item, ContextFilter) for item in handler.filters):
            handler.addFilter(filt)
    logger.propagate = False
    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    if name:
        return logging.getLogger(f"{_LOGGER_NAME}.{name}")
    return logging.getLogger(_LOGGER_NAME)
