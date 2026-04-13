"""Rolling baseline computation for z-score calculations."""

import statistics
from dataclasses import dataclass

from src.config.constants import BASELINE_MIN_DATAPOINTS, STD_FLOOR
from src.database.models import OptionsSnapshot
from src.exceptions import InsufficientDataError


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


def compute_thin_baseline(values: list[float]) -> BaselineStats | None:
    """Conservative baseline for 1-4 data points (below the normal threshold).

    Uses a wider std estimate to produce conservative z-scores for contracts
    with thin trading history — exactly the illiquid OTM options where
    insider activity is most likely to appear.  Returns None when *values*
    is empty.
    """
    if not values:
        return None
    n = len(values)
    mean = statistics.mean(values)
    if n == 1:
        std = max(mean * 0.5, STD_FLOOR)
    else:
        raw_std = statistics.pstdev(values, mu=mean)
        std = max(raw_std * 2.0, mean * 0.3, STD_FLOOR)
    return BaselineStats(mean=mean, std=std, n=n)


def z_score(observed: float, baseline: BaselineStats) -> float:
    """Compute the z-score for an observed value given baseline stats."""
    return (observed - baseline.mean) / baseline.std


# ---------------------------------------------------------------------------
# Helpers to extract metric series from snapshot history
# ---------------------------------------------------------------------------

def extract_volumes(snapshots: list[OptionsSnapshot]) -> list[float]:
    """Daily volumes from the baseline window, excluding zero-volume days."""
    return [float(s.volume) for s in snapshots if s.volume is not None and s.volume > 0]


def extract_open_interest(snapshots: list[OptionsSnapshot]) -> list[float]:
    """Open interest values from the baseline window."""
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


def extract_implied_volatility(snapshots: list[OptionsSnapshot]) -> list[float]:
    """Implied volatility values (decimal, e.g. 0.32 = 32%)."""
    return [float(s.implied_volatility) for s in snapshots
            if s.implied_volatility is not None and float(s.implied_volatility) > 0]


def extract_vol_oi_ratios(snapshots: list[OptionsSnapshot]) -> list[float]:
    """Volume / open-interest ratio for each day in the baseline.

    Both volume and OI use the same semantics across days (OI is always
    the prior-day settlement figure), so the ratio is consistent.
    """
    ratios: list[float] = []
    for s in snapshots:
        vol = s.volume or 0
        oi = s.open_interest or 0
        if oi > 0 and vol > 0:
            ratios.append(float(vol) / float(oi))
    return ratios
