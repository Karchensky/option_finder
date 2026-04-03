"""Tests for the already-priced-in gate."""

from src.scoring.gate import check_already_priced_in


def test_call_not_priced_in_small_move():
    assert check_already_priced_in("call", 1.0) is False


def test_call_priced_in_large_up_move():
    assert check_already_priced_in("call", 3.0) is True


def test_put_not_priced_in_small_move():
    assert check_already_priced_in("put", -1.0) is False


def test_put_priced_in_large_down_move():
    assert check_already_priced_in("put", -3.0) is True


def test_call_not_priced_in_when_stock_drops():
    assert check_already_priced_in("call", -5.0) is False


def test_put_not_priced_in_when_stock_rises():
    assert check_already_priced_in("put", 5.0) is False


def test_custom_threshold():
    assert check_already_priced_in("call", 6.0, threshold=0.05) is True
    assert check_already_priced_in("call", 4.0, threshold=0.05) is False
