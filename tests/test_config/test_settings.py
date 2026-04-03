"""Tests for configuration loading."""

from src.config.settings import Settings, get_settings


def test_settings_loads_from_env():
    settings = get_settings()
    assert settings.polygon_api_key == "test_api_key"
    assert settings.anomaly_alert_min_score == 7.5
    assert settings.anomaly_email_enabled is False


def test_async_database_url():
    settings = get_settings()
    url = settings.async_database_url
    assert url.startswith("postgresql+asyncpg://")


def test_defaults():
    settings = get_settings()
    assert settings.smtp_server == "smtp.gmail.com"
    assert settings.smtp_port == 465
    assert settings.polygon_flatfiles_endpoint == "https://files.polygon.io"
