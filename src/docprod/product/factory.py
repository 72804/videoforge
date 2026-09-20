from __future__ import annotations

from pathlib import Path

from docprod.config import Settings
from docprod.db.engine import make_engine, make_session_factory, uses_serverless_pool
from docprod.db.postgres_repo import PostgresRepository
from docprod.product.canary import parse_telegram_allowlist
from docprod.product.limits import ProductLimits
from docprod.product.persist import load_repository_file
from docprod.product.plans import PricingPolicy
from docprod.product.repository import MemoryRepository
from docprod.product.s3_storage import S3CompatibleStorage
from docprod.product.services import ProductService
from docprod.product.storage import (
    LocalStorageBackend,
    PlaceholderStorageBackend,
    StorageBackend,
)


def persistence_mode(settings: Settings) -> str:
    mode = (settings.product_persistence or "json").strip().lower()
    if mode not in {"json", "postgres"}:
        raise ValueError("PRODUCT_PERSISTENCE must be json or postgres")
    return mode


def build_repository(settings: Settings, *, store: Path | None = None) -> MemoryRepository:
    if persistence_mode(settings) == "postgres":
        serverless = settings.app_env.strip().lower() == "production" or uses_serverless_pool(
            settings.database_url
        )
        engine = make_engine(settings.database_url, serverless=serverless)
        return PostgresRepository(make_session_factory(engine))
    path = store or Path(settings.product_store_path or "product_data/store.json")
    return load_repository_file(path)


def build_storage(settings: Settings, *, store: Path | None = None) -> StorageBackend:
    if settings.s3_bucket.strip() and settings._secret_configured(settings.s3_access_key):
        secret = settings.s3_secret_key.get_secret_value() if settings.s3_secret_key else ""
        access = settings.s3_access_key.get_secret_value() if settings.s3_access_key else ""
        return S3CompatibleStorage(
            bucket=settings.s3_bucket.strip(),
            access_key=access.strip(),
            secret_key=secret.strip(),
            endpoint=settings.s3_endpoint.strip(),
            region=settings.s3_region.strip() or "auto",
            public_base=settings.s3_public_base.strip(),
        )
    if persistence_mode(settings) == "postgres":
        if settings.app_env.strip().lower() == "production":
            return PlaceholderStorageBackend()
        path = store or Path(settings.product_store_path or "product_data/store.json")
        return LocalStorageBackend(path.parent / "blobs")
    path = store or Path(settings.product_store_path or "product_data/store.json")
    return LocalStorageBackend(path.parent / "blobs")


def build_product_service(
    settings: Settings,
    *,
    store: Path | None = None,
    bot_token: str = "test-bot-token",
) -> ProductService:
    token = bot_token
    if settings.telegram_bot_token is not None:
        raw = settings.telegram_bot_token.get_secret_value().strip()
        if raw:
            token = raw
    return ProductService(
        build_repository(settings, store=store),
        storage=build_storage(settings, store=store),
        bot_token=token,
        limits=ProductLimits(
            init_data_max_age_seconds=settings.telegram_init_data_max_age_seconds,
            max_provider_usd_per_job=(
                min(ProductLimits().max_provider_usd_per_job, settings.canary_max_provider_usd)
                if settings.real_generation_canary
                else ProductLimits().max_provider_usd_per_job
            ),
        ),
        pricing=PricingPolicy(),
        generation_mode=settings.generation_mode.strip().lower() or "mock",
        real_generation_canary=settings.real_generation_canary,
        canary_telegram_ids=parse_telegram_allowlist(settings.generation_canary_telegram_ids),
    )
