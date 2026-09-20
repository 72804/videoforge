from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from docprod.exceptions import MissingApiKeyError, PaidApiDisabledError, PaidApiNotConfirmedError

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ENV_FILE = _REPO_ROOT / ".env"


class Settings(BaseSettings):
    """Runtime settings. Paid APIs stay disabled unless explicitly enabled."""

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE) if _ENV_FILE.is_file() else None,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
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
    research_provider: str = Field(default="openai")
    research_model: str = Field(default="gpt-5.6-luna")
    dossier_model: str = Field(default="gpt-5.6-luna")
    writer_model: str = Field(default="gpt-5.6-terra")
    scene_planner_model: str = Field(default="gpt-5.6-luna")
    research_max_tool_calls: int = Field(default=8)
    gemini_api_key: SecretStr | None = Field(default=None)
    video_provider: str = Field(default="google")
    video_model: str = Field(default="veo-3.1-lite-generate-preview")
    music_provider: str = Field(default="google")
    music_model: str = Field(default="lyria-3.5")
    music_preview_model: str = Field(default="lyria-3-clip-preview")
    adaptive_music_model: str = Field(default="lyria-realtime-exp")
    audio_embedding_model: str = Field(default="gemini-embedding-2")
    sound_library_matcher: str = Field(default="metadata")
    enable_lyria_realtime: bool = Field(default=False)
    enable_semantic_audio_qc: bool = Field(default=False)
    phase11_max_usd: float = Field(default=2.0)
    quality_profile: str = Field(default="balanced")
    elevenlabs_api_key: SecretStr | None = Field(default=None)
    elevenlabs_voice_id: str = Field(default="")
    higgsfield_api_key: SecretStr | None = Field(default=None)
    higgsfield_api_key_id: SecretStr | None = Field(default=None)
    higgsfield_api_key_secret: SecretStr | None = Field(default=None)
    runway_api_key: SecretStr | None = Field(default=None)
    anthropic_api_key: SecretStr | None = Field(default=None)
    local_llm_base_url: str = Field(default="")
    local_image_base_url: str = Field(default="")
    local_video_base_url: str = Field(default="")
    local_tts_base_url: str = Field(default="")
    local_music_base_url: str = Field(default="")
    quality_ping_local: bool = Field(default=False)
    app_env: str = Field(default="development")
    api_session_secret: SecretStr | None = Field(default=None)
    api_cors_origins: str = Field(
        default="",
        validation_alias=AliasChoices(
            "API_CORS_ORIGINS",
            "CORS_ALLOWED_ORIGINS",
            "api_cors_origins",
        ),
    )
    telegram_bot_token: SecretStr | None = Field(default=None)
    telegram_bot_username: str = Field(default="")
    telegram_mini_app_url: str = Field(default="")
    telegram_webhook_url: str = Field(default="")
    telegram_webhook_secret: SecretStr | None = Field(default=None)
    telegram_init_data_max_age_seconds: int = Field(default=86400)
    payment_mode: str = Field(default="simulated")
    generation_mode: str = Field(default="mock")
    allow_paid_generation: bool = Field(default=False)
    product_store_path: str = Field(default="")
    database_url: str = Field(default="")
    product_persistence: str = Field(default="json")
    worker_id: str = Field(default="")
    worker_poll_seconds: float = Field(default=1.0)
    job_lease_seconds: int = Field(default=30)
    job_execution_mode: str = Field(default="")
    internal_job_secret: SecretStr | None = Field(default=None)

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

    def gemini_key_configured(self) -> bool:
        secret = self.gemini_api_key
        if secret is None:
            return False
        return bool(secret.get_secret_value().strip())

    def _secret_configured(self, secret: SecretStr | None) -> bool:
        if secret is None:
            return False
        return bool(secret.get_secret_value().strip())

    def elevenlabs_key_configured(self) -> bool:
        return self._secret_configured(self.elevenlabs_api_key)

    def higgsfield_key_configured(self) -> bool:
        if self._secret_configured(self.higgsfield_api_key_id) and self._secret_configured(
            self.higgsfield_api_key_secret
        ):
            return True
        if not self._secret_configured(self.higgsfield_api_key):
            return False
        combined = self.higgsfield_api_key.get_secret_value()  # type: ignore[union-attr]
        return ":" in combined

    def runway_key_configured(self) -> bool:
        return self._secret_configured(self.runway_api_key)

    def anthropic_key_configured(self) -> bool:
        return self._secret_configured(self.anthropic_api_key)


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


def require_gemini_api_key(settings: Settings | None = None) -> str:
    cfg = settings if settings is not None else get_settings()
    if not cfg.gemini_key_configured():
        raise MissingApiKeyError(
            "GEMINI_API_KEY is not set. Add it to .env (never commit the file)."
        )
    return cfg.gemini_api_key.get_secret_value()  # type: ignore[union-attr]


def _secret(settings: Settings, field: str) -> str:
    secret = getattr(settings, field)
    if secret is None:
        return ""
    return secret.get_secret_value().strip()


def api_bind_address(
    *,
    host: str | None = None,
    port: int | None = None,
    app_env: str = "development",
    port_env: str | None = None,
) -> tuple[str, int]:
    """Local default 127.0.0.1:8000. Injected PORT binds 0.0.0.0."""
    env = app_env.strip().lower()
    injected = port_env if port_env is not None else os.environ.get("PORT", "")
    bind_port = int(port if port is not None else (str(injected).strip() or "8000"))
    if host:
        bind_host = host
    elif env == "production" or bool(str(injected).strip()):
        bind_host = "0.0.0.0"
    else:
        bind_host = "127.0.0.1"
    return bind_host, bind_port


def cors_origin_list(raw: str) -> list[str]:
    return [part.strip().rstrip("/") for part in raw.split(",") if part.strip()]


def resolve_job_execution_mode(settings: Settings) -> str:
    mode = settings.job_execution_mode.strip().lower()
    if mode in {"inline", "worker"}:
        return mode
    if settings.app_env.strip().lower() == "production":
        return "inline"
    return "worker"


def validate_runtime_settings(settings: Settings, *, role: str = "api") -> None:
    """Fail fast on illegal production payment/generation combinations.

    role=api applies webhook, session, and CORS checks.
    role=worker skips those API-only requirements.
    """
    env = settings.app_env.strip().lower()
    payment = settings.payment_mode.strip().lower() or "simulated"
    generation = settings.generation_mode.strip().lower() or "mock"
    if generation != "mock":
        raise RuntimeError("GENERATION_MODE must be mock until paid adapters are enabled.")
    if settings.allow_paid_generation:
        raise RuntimeError("ALLOW_PAID_GENERATION must be false until Phase 16.")
    if env in {"development", "test"}:
        return
    if settings.allow_paid_apis:
        raise RuntimeError("ALLOW_PAID_APIS must be false until Phase 16.")
    if payment == "simulated":
        raise RuntimeError("PAYMENT_MODE=simulated is not allowed in production.")
    if payment == "fake":
        raise RuntimeError("PAYMENT_MODE=fake is test-only.")
    if payment != "telegram":
        raise RuntimeError("PAYMENT_MODE must be telegram in production.")
    persistence = (settings.product_persistence or "").strip().lower()
    if persistence != "postgres":
        raise RuntimeError("PRODUCT_PERSISTENCE must be postgres in production.")
    if not settings.database_url.strip():
        raise RuntimeError("DATABASE_URL is required in production.")
    if not _secret(settings, "telegram_bot_token"):
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required for PAYMENT_MODE=telegram.")
    url = settings.telegram_mini_app_url.strip()
    if not url.startswith("https://"):
        raise RuntimeError("TELEGRAM_MINI_APP_URL must be https in production.")
    if role == "worker":
        return
    if not _secret(settings, "api_session_secret"):
        raise RuntimeError("API_SESSION_SECRET is required in production.")
    if not _secret(settings, "telegram_webhook_secret"):
        raise RuntimeError("TELEGRAM_WEBHOOK_SECRET is required in production.")
    if not _secret(settings, "internal_job_secret"):
        raise RuntimeError("INTERNAL_JOB_SECRET is required in production.")
    origins = cors_origin_list(settings.api_cors_origins)
    if not origins:
        raise RuntimeError("CORS_ALLOWED_ORIGINS is required in production.")
    if "*" in origins:
        raise RuntimeError("CORS wildcard origins are not allowed with credentialed cookies.")
