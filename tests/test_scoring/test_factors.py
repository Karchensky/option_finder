"""Tests for individual scoring factor calculators."""

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from src.scoring.factors import (
    compute_delta_concentration,
    compute_earnings_proximity,
    compute_iv_spike,
    compute_time_to_expiry,
    compute_underlying_move,
    compute_vol_oi_ratio,
)


def _make_option_snap(
    contract_type: str = "call",
    strike: float = 155.0,
    volume: int = 100,
    delta: float | None = None,
) -> MagicMock:
    snap = MagicMock()
    snap.contract_type = contract_type
    snap.strike_price = Decimal(str(strike))
    snap.volume = volume
    snap.delta = Decimal(str(delta)) if delta is not None else None
    return snap


def test_delta_concentration_deep_otm_by_delta():
    snaps = [
        _make_option_snap("call", 200.0, 500, delta=0.05),
        _make_option_snap("call", 210.0, 300, delta=0.03),
    ]
    result = compute_delta_concentration(snaps, underlying_price=150.0)
    assert result.raw == 1.0  # 100% deep OTM by delta


def test_delta_concentration_atm_by_delta():
    snaps = [
        _make_option_snap("call", 150.0, 500, delta=0.50),
        _make_option_snap("call", 155.0, 300, delta=0.45),
    ]
    result = compute_delta_concentration(snaps, underlying_price=150.0)
    assert result.raw == 0.0  # 0% deep OTM


def test_delta_concentration_fallback_to_price():
    """Without delta, uses strike > 1.10 * underlying for calls."""
    snaps = [
        _make_option_snap("call", 170.0, 500, delta=None),  # 170 > 150*1.10=165 -> OTM
        _make_option_snap("call", 155.0, 500, delta=None),  # 155 < 165 -> not deep OTM
    ]
    result = compute_delta_concentration(snaps, underlying_price=150.0)
    assert result.raw == pytest.approx(0.5)


def test_delta_concentration_no_volume():
    snaps = [_make_option_snap("call", 160.0, 0, delta=0.05)]
    result = compute_delta_concentration(snaps, underlying_price=150.0)
    assert result.raw == 0.0
    assert result.z_score == 0.0


def test_time_to_expiry_short_dated():
    result = compute_time_to_expiry(date(2026, 4, 10), date(2026, 4, 3))
    assert result.raw == 7.0
    assert result.z_score == pytest.approx(1.0)


def test_time_to_expiry_long_dated():
    result = compute_time_to_expiry(date(2026, 7, 1), date(2026, 4, 3))
    assert result.raw == 89.0
    assert result.z_score < 0


def test_underlying_move_call_up():
    result = compute_underlying_move(1.5, "call")
    assert result.contribution > 0


def test_underlying_move_put_down():
    result = compute_underlying_move(-1.5, "put")
    assert result.contribution > 0


def test_underlying_move_zero():
    result = compute_underlying_move(0.0, "call")
    assert result.z_score == 0.0


def test_earnings_proximity_no_earnings():
    result = compute_earnings_proximity(None)
    assert result.z_score == 0.0
    assert result.contribution == 0.0


def test_earnings_proximity_imminent():
    result = compute_earnings_proximity(0)
    assert result.z_score < 0
    assert result.z_score == pytest.approx(-3.5)


def test_earnings_proximity_one_week():
    result = compute_earnings_proximity(7)
    assert result.z_score < 0
    assert result.z_score == pytest.approx(-1.75)


def test_earnings_proximity_beyond_window():
    result = compute_earnings_proximity(21)
    assert result.z_score == 0.0


def test_earnings_proximity_recent_past():
    result = compute_earnings_proximity(-2)
    assert result.z_score < 0
    assert result.z_score == pytest.approx(-1 / 3)


def test_iv_spike_zero_iv():
    result = compute_iv_spike(0.0, [])
    assert result.z_score == 0.0


def test_vol_oi_ratio_no_oi():
    result = compute_vol_oi_ratio(100, 0, [])
    assert result.raw == 100.0
