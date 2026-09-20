from docprod.config import (
    Settings,
    api_bind_address,
    resolve_job_execution_mode,
    validate_runtime_settings,
)
from docprod.db.engine import make_engine, sqlalchemy_database_url, uses_serverless_pool


def _prod(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_env": "production",
        "payment_mode": "telegram",
        "generation_mode": "mock",
        "allow_paid_generation": False,
        "allow_paid_apis": False,
        "product_persistence": "postgres",
        "database_url": "postgresql://u:p@localhost/db",
        "telegram_bot_token": "placeholder-token",
        "telegram_mini_app_url": "https://app.example",
        "api_session_secret": "session-secret",
        "telegram_webhook_secret": "webhook-secret",
        "internal_job_secret": "internal-job-secret",
        "api_cors_origins": "https://app.example",
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


def test_production_rejects_simulated_payment() -> None:
    settings = Settings(app_env="production", payment_mode="simulated", _env_file=None)
    try:
        validate_runtime_settings(settings)
    except RuntimeError as exc:
        assert "simulated" in str(exc).lower()
    else:
        raise AssertionError("expected failure")


def test_development_allows_simulated() -> None:
    settings = Settings(app_env="development", payment_mode="simulated", _env_file=None)
    validate_runtime_settings(settings)


def test_production_api_requires_postgres_cors_and_secrets() -> None:
    try:
        validate_runtime_settings(_prod(product_persistence="json"))
    except RuntimeError as exc:
        assert "postgres" in str(exc).lower()
    else:
        raise AssertionError("expected failure")
    try:
        validate_runtime_settings(_prod(api_cors_origins="*"))
    except RuntimeError as exc:
        assert "wildcard" in str(exc).lower()
    else:
        raise AssertionError("expected failure")
    validate_runtime_settings(_prod())


def test_worker_skips_api_only_secrets() -> None:
    settings = _prod(
        api_session_secret=None,
        telegram_webhook_secret=None,
        api_cors_origins="",
    )
    validate_runtime_settings(settings, role="worker")
    try:
        validate_runtime_settings(settings, role="api")
    except RuntimeError:
        pass
    else:
        raise AssertionError("api role should require webhook/session")
    try:
        validate_runtime_settings(_prod(internal_job_secret=None), role="api")
    except RuntimeError as exc:
        assert "INTERNAL_JOB_SECRET" in str(exc)
    else:
        raise AssertionError("api role should require INTERNAL_JOB_SECRET")
    validate_runtime_settings(_prod(api_cors_origins=""))


def test_production_rejects_paid_flags() -> None:
    try:
        validate_runtime_settings(_prod(allow_paid_apis=True))
    except RuntimeError as exc:
        assert "ALLOW_PAID_APIS" in str(exc)
    else:
        raise AssertionError("expected failure")
    try:
        validate_runtime_settings(_prod(allow_paid_generation=True))
    except RuntimeError as exc:
        assert "ALLOW_PAID_GENERATION" in str(exc)
    else:
        raise AssertionError("expected failure")


def test_bind_address_uses_port_env() -> None:
    host, port = api_bind_address(app_env="development")
    assert host == "127.0.0.1"
    assert port == 8000
    host, port = api_bind_address(app_env="production", port_env="8080")
    assert host == "0.0.0.0"
    assert port == 8080
    host, port = api_bind_address(host="127.0.0.1", port=9000, port_env="8080")
    assert host == "127.0.0.1"
    assert port == 9000


def test_neon_postgres_url_normalized() -> None:
    neon = (
        "postgres://u:p@ep-abc-pooler.us-east-1.aws.neon.tech/neondb?sslmode=require"
    )
    converted = sqlalchemy_database_url(neon)
    assert converted.startswith("postgresql+psycopg://")
    assert "sslmode=require" in converted
    assert uses_serverless_pool(converted)
    assert uses_serverless_pool(
        "postgresql://u:p@ep-abc.region.aws.neon.tech/db?pgbouncer=true"
    )
    engine = make_engine(neon, serverless=True)
    assert engine.pool.__class__.__name__ == "NullPool"
    local = make_engine("postgresql://u:p@127.0.0.1/docprod", serverless=False)
    assert local.pool.__class__.__name__ != "NullPool"


def test_job_execution_mode_defaults() -> None:
    assert (
        resolve_job_execution_mode(_prod()) == "inline"
    )
    assert (
        resolve_job_execution_mode(
            Settings(app_env="development", job_execution_mode="", _env_file=None)
        )
        == "worker"
    )
    assert resolve_job_execution_mode(_prod(job_execution_mode="worker")) == "worker"


def test_railway_postgres_url_normalized() -> None:
    assert sqlalchemy_database_url("postgres://u:p@host/db").startswith(
        "postgresql+psycopg://"
    )
    assert sqlalchemy_database_url("postgresql://u:p@host/db").startswith(
        "postgresql+psycopg://"
    )
    assert "+psycopg" in sqlalchemy_database_url("postgresql+psycopg://u:p@host/db")
