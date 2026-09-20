from docprod.config import Settings, validate_runtime_settings


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
