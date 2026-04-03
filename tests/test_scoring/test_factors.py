"""Tests for individual scoring factor calculators."""

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from src.scoring.factors import (
    compute_otm_clustering,
    compute_time_to_expiry,
    compute_underlying_move,
)


def _make_option_snap(
    contract_type: str = "call",
    strike: float = 155.0,
    volume: int = 100,
) -> MagicMock:
    snap = MagicMock()
    snap.contract_type = contract_type
    snap.strike_price = Decimal(str(strike))
    snap.volume = volume
    return snap


def test_otm_clustering_all_otm_calls():
    snaps = [
        _make_option_snap("call", 160.0, 500),
        _make_option_snap("call", 170.0, 300),
    ]
    result = compute_otm_clustering(snaps, underlying_price=150.0)
    assert result.raw == 1.0  # 100% OTM


def test_otm_clustering_all_itm_calls():
    snaps = [
        _make_option_snap("call", 140.0, 500),
        _make_option_snap("call", 130.0, 300),
    ]
    result = compute_otm_clustering(snaps, underlying_price=150.0)
    assert result.raw == 0.0  # 0% OTM


def test_otm_clustering_mixed():
    snaps = [
        _make_option_snap("call", 160.0, 500),  # OTM
        _make_option_snap("call", 140.0, 500),  # ITM
    ]
    result = compute_otm_clustering(snaps, underlying_price=150.0)
    assert result.raw == pytest.approx(0.5)


def test_otm_clustering_no_volume():
    snaps = [_make_option_snap("call", 160.0, 0)]
    result = compute_otm_clustering(snaps, underlying_price=150.0)
    assert result.raw == 0.0
    assert result.z_score == 0.0


def test_time_to_expiry_short_dated():
    result = compute_time_to_expiry(date(2026, 4, 10), date(2026, 4, 3))
    assert result.raw == 7.0
    assert result.z_score == pytest.approx(1.0)


def test_time_to_expiry_long_dated():
    result = compute_time_to_expiry(date(2026, 7, 1), date(2026, 4, 3))
    assert result.raw == 89.0
    assert result.z_score < 0  # long-dated = lower signal


def test_underlying_move_call_up():
    result = compute_underlying_move(1.5, "call")
    assert result.contribution > 0


def test_underlying_move_put_down():
    result = compute_underlying_move(-1.5, "put")
    assert result.contribution > 0


def test_underlying_move_zero():
    result = compute_underlying_move(0.0, "call")
    assert result.z_score == 0.0
