"""Shared pytest fixtures for Option Finder tests."""

import os
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _set_test_env(monkeypatch):
    """Ensure test environment variables are set so Settings can load."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost:5432/test_option_finder")
    monkeypatch.setenv("POLYGON_API_KEY", "test_api_key")
    monkeypatch.setenv("SENDER_EMAIL", "test@example.com")
    monkeypatch.setenv("EMAIL_PASSWORD", "testpass")
    monkeypatch.setenv("RECIPIENT_EMAIL", "recipient@example.com")
    monkeypatch.setenv("ANOMALY_EMAIL_ENABLED", "false")
    monkeypatch.setenv("ANOMALY_ALERT_MIN_SCORE", "7.5")

    from src.config.settings import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def sample_stock_snapshot_row() -> dict:
    return {
        "ticker": "AAPL",
        "snap_date": date(2026, 4, 1),
        "open": Decimal("150.00"),
        "high": Decimal("155.00"),
        "low": Decimal("149.00"),
        "close": Decimal("154.00"),
        "volume": 50_000_000,
        "vwap": Decimal("152.50"),
        "change_pct": Decimal("2.50"),
        "prev_close": Decimal("150.25"),
    }


@pytest.fixture()
def sample_option_snapshot_row() -> dict:
    return {
        "option_ticker": "O:AAPL260401C00155000",
        "underlying_ticker": "AAPL",
        "snap_date": date(2026, 4, 1),
        "contract_type": "call",
        "strike_price": Decimal("155.00"),
        "expiration_date": date(2026, 4, 17),
        "open": Decimal("3.00"),
        "high": Decimal("4.50"),
        "low": Decimal("2.80"),
        "close": Decimal("4.20"),
        "volume": 5000,
        "vwap": Decimal("3.80"),
        "open_interest": 12000,
        "implied_volatility": Decimal("0.350000"),
        "delta": Decimal("0.450000"),
        "gamma": Decimal("0.030000"),
        "theta": Decimal("-0.050000"),
        "vega": Decimal("0.150000"),
        "bid": Decimal("4.10"),
        "ask": Decimal("4.30"),
        "break_even_price": Decimal("159.20"),
        "underlying_price": Decimal("154.00"),
    }
