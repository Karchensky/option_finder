"""Rolling baseline computation for z-score calculations."""

import logging
import statistics
from dataclasses import dataclass

from src.config.constants import BASELINE_MIN_DATAPOINTS, STD_FLOOR
from src.database.models import OptionsSnapshot
from src.exceptions import InsufficientDataError

logger = logging.getLogger(__name__)


@dataclass
class BaselineStats:
    """Mean and clamped standard deviation for a single metric."""

    mean: float
    std: float
    n: int


def compute_baseline(values: list[float], ticker: str = "") -> BaselineStats:
    """Compute mean and std over *values*, raising if too few data points.

    The standard deviation is floored at STD_FLOOR to prevent division by zero.
    """
    n = len(values)
    if n < BASELINE_MIN_DATAPOINTS:
        raise InsufficientDataError(ticker=ticker, available=n)

    mean = statistics.mean(values)
    std = max(statistics.pstdev(values, mu=mean), STD_FLOOR)
    return BaselineStats(mean=mean, std=std, n=n)


def z_score(observed: float, baseline: BaselineStats) -> float:
    """Compute the z-score for an observed value given baseline stats."""
    return (observed - baseline.mean) / baseline.std


# ---------------------------------------------------------------------------
# Helpers to extract metric series from snapshot history
# ---------------------------------------------------------------------------

def extract_volumes(snapshots: list[OptionsSnapshot]) -> list[float]:
    return [float(s.volume) for s in snapshots if s.volume is not None and s.volume > 0]


def extract_open_interest(snapshots: list[OptionsSnapshot]) -> list[float]:
    return [float(s.open_interest) for s in snapshots if s.open_interest is not None]


def extract_premiums(snapshots: list[OptionsSnapshot]) -> list[float]:
    """Dollar premium = close price * volume * 100 (shares per contract)."""
    premiums: list[float] = []
    for s in snapshots:
        if s.close is not None and s.volume is not None and s.volume > 0:
            premiums.append(float(s.close) * float(s.volume) * 100)
    return premiums


def extract_spreads(snapshots: list[OptionsSnapshot]) -> list[float]:
    """Bid-ask spread in dollars."""
    spreads: list[float] = []
    for s in snapshots:
        if s.bid is not None and s.ask is not None:
            spread = float(s.ask) - float(s.bid)
            if spread >= 0:
                spreads.append(spread)
    return spreads
