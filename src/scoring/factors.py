"""Individual factor calculators — each returns a FactorScore."""

import logging
from datetime import date

from src.config.constants import FACTOR_WEIGHT_MAP, STD_FLOOR
from src.database.models import OptionsSnapshot
from src.scoring.baseline import (
    BaselineStats,
    compute_baseline,
    extract_open_interest,
    extract_premiums,
    extract_spreads,
    extract_volumes,
    z_score,
)
from src.scoring.models import FactorScore

logger = logging.getLogger(__name__)


def _make_factor(key: str, raw: float, z: float) -> FactorScore:
    w = FACTOR_WEIGHT_MAP.get(key, 0.0)
    return FactorScore(raw=raw, z_score=z, weight=w, contribution=z * w)


# ---------------------------------------------------------------------------
# Tier 1 — High signal
# ---------------------------------------------------------------------------

def compute_volume_spike(
    current_volume: int,
    baseline_snapshots: list[OptionsSnapshot],
    ticker: str = "",
) -> FactorScore:
    """Contract volume vs 20-day average."""
    volumes = extract_volumes(baseline_snapshots)
    bl = compute_baseline(volumes, ticker=ticker)
    z = z_score(float(current_volume), bl)
    return _make_factor("vol_z", float(current_volume), z)


def compute_premium_surge(
    current_close: float,
    current_volume: int,
    baseline_snapshots: list[OptionsSnapshot],
    ticker: str = "",
) -> FactorScore:
    """Dollar premium (price * volume * 100) vs 20-day average."""
    current_premium = current_close * current_volume * 100
    premiums = extract_premiums(baseline_snapshots)
    bl = compute_baseline(premiums, ticker=ticker)
    z = z_score(current_premium, bl)
    return _make_factor("prem_z", current_premium, z)


def compute_sweep_detection(
    current_volume: int,
    baseline_snapshots: list[OptionsSnapshot],
    ticker: str = "",
) -> FactorScore:
    """Placeholder sweep detection based on volume extremity.

    True sweep detection requires trade-level condition codes and
    multi-exchange fill clustering. For the initial build we use
    volume as a proxy — a very high volume z-score implies aggressive
    buying consistent with sweep-like behaviour.
    """
    volumes = extract_volumes(baseline_snapshots)
    bl = compute_baseline(volumes, ticker=ticker)
    z = z_score(float(current_volume), bl)
    sweep_z = max(z - 2.0, 0.0)  # only contributes when volume is 2+ sigma above mean
    return _make_factor("sweep_z", float(current_volume), sweep_z)


# ---------------------------------------------------------------------------
# Tier 2 — Medium signal
# ---------------------------------------------------------------------------

def compute_oi_change(
    current_oi: int,
    baseline_snapshots: list[OptionsSnapshot],
    ticker: str = "",
) -> FactorScore:
    """Day-over-day open interest delta vs 20-day average delta."""
    ois = extract_open_interest(baseline_snapshots)
    if len(ois) < 2:
        return _make_factor("oi_z", float(current_oi), 0.0)

    deltas = [ois[i] - ois[i + 1] for i in range(len(ois) - 1)]
    prev_oi = ois[0] if ois else float(current_oi)
    current_delta = float(current_oi) - prev_oi

    bl = compute_baseline(deltas, ticker=ticker)
    z = z_score(current_delta, bl)
    return _make_factor("oi_z", current_delta, z)


def compute_otm_clustering(
    chain_snapshots: list[OptionsSnapshot],
    underlying_price: float,
) -> FactorScore:
    """Fraction of chain volume that is OTM.

    Calls are OTM when strike > underlying; puts are OTM when strike < underlying.
    A high OTM concentration raises the signal.
    """
    total_vol = 0
    otm_vol = 0

    for snap in chain_snapshots:
        vol = snap.volume or 0
        if vol == 0:
            continue
        total_vol += vol
        strike = float(snap.strike_price)
        is_call = snap.contract_type.lower() == "call"
        if (is_call and strike > underlying_price) or (not is_call and strike < underlying_price):
            otm_vol += vol

    if total_vol == 0:
        return _make_factor("otm_z", 0.0, 0.0)

    otm_frac = otm_vol / total_vol
    # Z-score against a naive 50/50 assumption; std floor prevents /0
    z = (otm_frac - 0.5) / max(0.15, STD_FLOOR)
    return _make_factor("otm_z", otm_frac, z)


def compute_time_to_expiry(
    expiration_date: date,
    current_date: date,
) -> FactorScore:
    """Shorter DTE = stronger signal. < 14 DTE yields positive z-score."""
    dte = max((expiration_date - current_date).days, 0)
    # Invert: fewer days = higher signal. Use 14 as midpoint, 7 as std.
    z = (14.0 - dte) / 7.0
    return _make_factor("tte_z", float(dte), z)


# ---------------------------------------------------------------------------
# Tier 3 — Supporting signals
# ---------------------------------------------------------------------------

def compute_spread(
    current_bid: float | None,
    current_ask: float | None,
    baseline_snapshots: list[OptionsSnapshot],
    ticker: str = "",
) -> FactorScore:
    """Tighter-than-normal bid-ask spread on unusual volume."""
    if current_bid is None or current_ask is None:
        return _make_factor("spread_z", 0.0, 0.0)

    current_spread = current_ask - current_bid
    if current_spread < 0:
        return _make_factor("spread_z", current_spread, 0.0)

    spreads = extract_spreads(baseline_snapshots)
    if len(spreads) < 5:
        return _make_factor("spread_z", current_spread, 0.0)

    bl = compute_baseline(spreads, ticker=ticker)
    # Invert: tighter spread = higher signal → negate the z-score
    z = -z_score(current_spread, bl)
    return _make_factor("spread_z", current_spread, z)


def compute_underlying_move(
    underlying_change_pct: float,
    contract_type: str,
) -> FactorScore:
    """Stock move correlated with options bet direction.

    Positive contribution when stock moves in the same direction as
    the bet (calls + stock up, puts + stock down).
    """
    is_call = contract_type.lower() == "call"
    directional = underlying_change_pct if is_call else -underlying_change_pct
    z = directional / max(abs(underlying_change_pct), STD_FLOOR) if underlying_change_pct != 0 else 0.0
    return _make_factor("underlying_z", underlying_change_pct, z)
