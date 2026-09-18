from __future__ import annotations

import os
from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from docprod.exceptions import MissingApiKeyError, PaidApiDisabledError, PaidApiNotConfirmedError


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
    image_provider: str = Field(default="openai")
    openai_api_key: SecretStr | None = Field(default=None)
    openai_image_model: str = Field(default="gpt-image-2.5-flare")
    openai_image_size: str = Field(default="1536x864")
    openai_image_quality: str = Field(default="medium")
    openai_image_output_format: str = Field(default="jpeg")
    pexels_api_key: SecretStr | None = Field(default=None)
    openai_tts_model: str = Field(default="gpt-4o-mini-tts")
    openai_tts_voice: str = Field(default="cedar")
    openai_tts_speed: float = Field(default=1.0)

    def openai_key_configured(self) -> bool:
        secret = self.openai_api_key
        if secret is None:
            return False
        return bool(secret.get_secret_value().strip())

    def pexels_key_configured(self) -> bool:
        secret = self.pexels_api_key
        if secret is None:
            return False
        return bool(secret.get_secret_value().strip())


@lru_cache
def get_settings() -> Settings:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return Settings(_env_file=None)
    return Settings()


def require_paid_apis_enabled(provider_name: str, settings: Settings | None = None) -> None:
    """Central safety gate for paid provider adapters.

    Raises unless ALLOW_PAID_APIS=true.
    """
    cfg = settings if settings is not None else get_settings()
    if not cfg.allow_paid_apis:
        raise PaidApiDisabledError(
            f"Paid API access is disabled for provider {provider_name!r}. "
            "Set ALLOW_PAID_APIS=true only when you intentionally allow billed calls."
        )


def require_paid_call_allowed(
    provider_name: str,
    *,
    confirm_paid: bool,
    settings: Settings | None = None,
) -> None:
    require_paid_apis_enabled(provider_name, settings)
    if not confirm_paid:
        raise PaidApiNotConfirmedError(
            f"Paid call to {provider_name!r} requires --confirm-paid in addition to "
            "ALLOW_PAID_APIS=true."
        )


def require_pexels_api_key(settings: Settings | None = None) -> str:
    cfg = settings if settings is not None else get_settings()
    if not cfg.pexels_key_configured():
        raise MissingApiKeyError(
            "PEXELS_API_KEY is not set. Add it to .env (never commit the file)."
        )
    return cfg.pexels_api_key.get_secret_value()  # type: ignore[union-attr]


def require_openai_api_key(settings: Settings | None = None) -> str:
    cfg = settings if settings is not None else get_settings()
    if not cfg.openai_key_configured():
        raise MissingApiKeyError(
            "OPENAI_API_KEY is not set. Add it to .env (never commit the file)."
        )
    return cfg.openai_api_key.get_secret_value()  # type: ignore[union-attr]
