from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from docprod.exceptions import PaidApiDisabledError


class Settings(BaseSettings):
    """Runtime settings. Paid APIs stay disabled unless explicitly enabled."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    allow_paid_apis: bool = Field(default=False)
    log_level: str = Field(default="INFO")


@lru_cache
def get_settings() -> Settings:
    return Settings()


def require_paid_apis_enabled(provider_name: str, settings: Settings | None = None) -> None:
    """Central safety gate for future paid provider adapters.

    Raises unless ALLOW_PAID_APIS=true.
    """
    cfg = settings if settings is not None else get_settings()
    if not cfg.allow_paid_apis:
        raise PaidApiDisabledError(
            f"Paid API access is disabled for provider {provider_name!r}. "
            "Set ALLOW_PAID_APIS=true only when you intentionally allow billed calls."
        )
