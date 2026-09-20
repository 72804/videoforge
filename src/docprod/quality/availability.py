from __future__ import annotations

from dataclasses import dataclass

from docprod.config import Settings, get_settings
from docprod.quality.enums import ProviderStatus
from docprod.quality.specs import ProviderSpec

PROVIDERS: tuple[ProviderSpec, ...] = (
    ProviderSpec(provider_id="openai", display_name="OpenAI", env_key="openai"),
    ProviderSpec(provider_id="google", display_name="Google Gemini/Veo/Lyria", env_key="gemini"),
    ProviderSpec(provider_id="anthropic", display_name="Anthropic", env_key="anthropic"),
    ProviderSpec(provider_id="elevenlabs", display_name="ElevenLabs", env_key="elevenlabs"),
    ProviderSpec(provider_id="higgsfield", display_name="Higgsfield", env_key="higgsfield"),
    ProviderSpec(provider_id="runway", display_name="Runway", env_key="runway"),
    ProviderSpec(provider_id="stability", display_name="Stability", env_key="stability"),
    ProviderSpec(provider_id="local", display_name="Local inference", local_url_attr="any"),
)


def _key_status(settings: Settings, name: str) -> ProviderStatus:
    mapping = {
        "openai": settings.openai_key_configured(),
        "gemini": settings.gemini_key_configured(),
        "google": settings.gemini_key_configured(),
        "anthropic": settings.anthropic_key_configured(),
        "elevenlabs": settings.elevenlabs_key_configured(),
        "higgsfield": settings.higgsfield_key_configured(),
        "runway": settings.runway_key_configured(),
        "stability": False,
        "pexels": settings.pexels_key_configured(),
    }
    if mapping.get(name):
        return ProviderStatus.CONFIGURED
    return ProviderStatus.UNCONFIGURED


def local_endpoint_status(settings: Settings | None = None) -> dict[str, ProviderStatus]:
    cfg = settings or get_settings()
    urls = {
        "llm": cfg.local_llm_base_url.strip(),
        "image": cfg.local_image_base_url.strip(),
        "video": cfg.local_video_base_url.strip(),
        "tts": cfg.local_tts_base_url.strip(),
        "music": cfg.local_music_base_url.strip(),
    }
    out: dict[str, ProviderStatus] = {}
    for name, url in urls.items():
        if not url:
            out[name] = ProviderStatus.UNCONFIGURED
        else:
            out[name] = ProviderStatus.CONFIGURED
            if cfg.quality_ping_local:
                out[name] = ping_url(url)
    return out


def ping_url(url: str, timeout: float = 0.4) -> ProviderStatus:
    """Optional health check. Off unless QUALITY_PING_LOCAL is set."""
    from urllib.error import URLError
    from urllib.request import Request, urlopen

    try:
        req = Request(url, method="GET")
        with urlopen(req, timeout=timeout):  # noqa: S310 — operator-configured endpoint
            return ProviderStatus.ONLINE
    except (URLError, TimeoutError, OSError, ValueError):
        return ProviderStatus.OFFLINE


@dataclass(frozen=True)
class AvailabilityReport:
    providers: dict[str, ProviderStatus]
    local_endpoints: dict[str, ProviderStatus]


def availability(settings: Settings | None = None) -> AvailabilityReport:
    cfg = settings or get_settings()
    providers = {
        "openai": _key_status(cfg, "openai"),
        "google": _key_status(cfg, "google"),
        "anthropic": _key_status(cfg, "anthropic"),
        "elevenlabs": _key_status(cfg, "elevenlabs"),
        "higgsfield": _key_status(cfg, "higgsfield"),
        "runway": _key_status(cfg, "runway"),
        "stability": ProviderStatus.UNCONFIGURED,
        "local": (
            ProviderStatus.CONFIGURED
            if any(
                url.strip()
                for url in (
                    cfg.local_llm_base_url,
                    cfg.local_image_base_url,
                    cfg.local_video_base_url,
                    cfg.local_tts_base_url,
                    cfg.local_music_base_url,
                )
            )
            else ProviderStatus.UNCONFIGURED
        ),
    }
    return AvailabilityReport(providers=providers, local_endpoints=local_endpoint_status(cfg))
