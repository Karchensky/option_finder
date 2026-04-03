"""Tests for Pydantic API response validation."""

from src.ingestion.schemas import (
    MarketStatus,
    OptionDetails,
    OptionSnapshotResult,
    StockDayBar,
    StockTickerSnapshot,
)


def test_stock_snapshot_parse():
    raw = {
        "ticker": "AAPL",
        "day": {"o": 150.0, "h": 155.0, "l": 149.0, "c": 154.0, "v": 50000000, "vw": 152.5},
        "prev_day": {"o": 148.0, "h": 151.0, "l": 147.0, "c": 150.0, "v": 40000000, "vw": 149.0},
        "todaysChange": 4.0,
        "todaysChangePerc": 2.67,
        "updated": 1700000000000000000,
    }
    snap = StockTickerSnapshot.model_validate(raw)
    assert snap.ticker == "AAPL"
    assert snap.day is not None
    assert float(snap.day.o) == 150.0
    assert float(snap.todaysChangePerc) == 2.67


def test_option_snapshot_parse():
    raw = {
        "break_even_price": 159.2,
        "day": {"open": 3.0, "high": 4.5, "low": 2.8, "close": 4.2, "volume": 5000, "vwap": 3.8},
        "details": {
            "contract_type": "call",
            "exercise_style": "american",
            "expiration_date": "2026-04-17",
            "shares_per_contract": 100,
            "strike_price": 155,
            "ticker": "O:AAPL260417C00155000",
        },
        "greeks": {"delta": 0.45, "gamma": 0.03, "theta": -0.05, "vega": 0.15},
        "implied_volatility": 0.35,
        "open_interest": 12000,
        "underlying_asset": {"ticker": "AAPL", "price": 154.0, "change_to_break_even": 5.2},
    }
    snap = OptionSnapshotResult.model_validate(raw)
    assert snap.details.ticker == "O:AAPL260417C00155000"
    assert snap.details.contract_type == "call"
    assert float(snap.details.strike_price) == 155.0
    assert snap.open_interest == 12000


def test_market_status_parse():
    raw = {"market": "open", "earlyHours": False, "afterHours": False, "serverTime": "2026-04-03T12:00:00-04:00"}
    status = MarketStatus.model_validate(raw)
    assert status.market == "open"
    assert status.earlyHours is False


def test_stock_snapshot_missing_optional_fields():
    raw = {"ticker": "XYZ"}
    snap = StockTickerSnapshot.model_validate(raw)
    assert snap.ticker == "XYZ"
    assert snap.day is None
    assert snap.todaysChangePerc is None
