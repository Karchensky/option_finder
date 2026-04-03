"""Tests for baseline computation and z-score calculation."""

import pytest

from src.config.constants import BASELINE_MIN_DATAPOINTS, STD_FLOOR
from src.exceptions import InsufficientDataError
from src.scoring.baseline import BaselineStats, compute_baseline, z_score


def test_compute_baseline_normal():
    values = [10.0, 12.0, 8.0, 11.0, 9.0, 10.5, 11.5, 8.5, 12.5, 9.5]
    bl = compute_baseline(values)
    assert bl.n == 10
    assert 9.0 < bl.mean < 11.0
    assert bl.std > STD_FLOOR


def test_compute_baseline_insufficient_data():
    with pytest.raises(InsufficientDataError) as exc_info:
        compute_baseline([1.0, 2.0], ticker="TEST")
    assert exc_info.value.available == 2
    assert exc_info.value.required == BASELINE_MIN_DATAPOINTS


def test_compute_baseline_std_floor():
    values = [5.0] * 10
    bl = compute_baseline(values)
    assert bl.std == STD_FLOOR
    assert bl.mean == 5.0


def test_z_score_positive():
    bl = BaselineStats(mean=10.0, std=2.0, n=20)
    z = z_score(14.0, bl)
    assert z == pytest.approx(2.0)


def test_z_score_negative():
    bl = BaselineStats(mean=10.0, std=2.0, n=20)
    z = z_score(6.0, bl)
    assert z == pytest.approx(-2.0)


def test_z_score_zero():
    bl = BaselineStats(mean=10.0, std=2.0, n=20)
    z = z_score(10.0, bl)
    assert z == pytest.approx(0.0)
