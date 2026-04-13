"""Individual factor calculators -- each returns a FactorScore."""

import logging
from datetime import date

from src.config.constants import BASELINE_MIN_DATAPOINTS, FACTOR_WEIGHT_MAP, STD_FLOOR, Z_SCORE_CAP
from src.database.models import OptionsSnapshot
from src.exceptions import InsufficientDataError
from src.scoring.baseline import (
    BaselineStats,
    compute_baseline,
    compute_thin_baseline,
    extract_implied_volatility,
    extract_open_interest,
    extract_premiums,
    extract_spreads,
    extract_vol_oi_ratios,
    extract_volumes,
    z_score,
)
from src.scoring.models import FactorScore

logger = logging.getLogger(__name__)


def _clamp_z(z: float) -> float:
    """Clamp z-score to [-Z_SCORE_CAP, Z_SCORE_CAP] to prevent single-factor blowout."""
    return max(-Z_SCORE_CAP, min(Z_SCORE_CAP, z))


def _make_factor(key: str, raw: float, z: float) -> FactorScore:
    w = FACTOR_WEIGHT_MAP.get(key, 0.0)
    z = _clamp_z(z)
    return FactorScore(raw=raw, z_score=z, weight=w, contribution=z * w)


# ---------------------------------------------------------------------------
# Tier 1 -- High signal
# ---------------------------------------------------------------------------

def compute_volume_spike(
    current_volume: int,
    baseline_snapshots: list[OptionsSnapshot],
    ticker: str = "",
) -> FactorScore:
    """Contract volume vs 20-day average.

    Falls back to a conservative thin-baseline heuristic for contracts
    with 1-4 data points, capturing sudden activity in normally illiquid
    options where insider trading often occurs.
    """
    volumes = extract_volumes(baseline_snapshots)
    try:
        bl = compute_baseline(volumes, ticker=ticker)
    except InsufficientDataError:
        bl = compute_thin_baseline(volumes)
        if bl is None:
            return _make_factor("vol_z", float(current_volume), 0.0)
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
    try:
        bl = compute_baseline(premiums, ticker=ticker)
    except InsufficientDataError:
        bl = compute_thin_baseline(premiums)
        if bl is None:
            return _make_factor("prem_z", current_premium, 0.0)
    z = z_score(current_premium, bl)
    return _make_factor("prem_z", current_premium, z)


def compute_iv_spike(
    current_iv: float,
    baseline_snapshots: list[OptionsSnapshot],
    ticker: str = "",
) -> FactorScore:
    """Implied volatility vs its own 20-day baseline.

    A surging IV relative to recent history signals the market is pricing
    in an imminent event -- strong signal independent of volume.

    Falls back to a conservative thin-baseline heuristic for contracts
    with 1-4 IV data points, consistent with vol_z and prem_z.
    """
    if current_iv <= 0:
        return _make_factor("iv_z", 0.0, 0.0)

    ivs = extract_implied_volatility(baseline_snapshots)
    try:
        bl = compute_baseline(ivs, ticker=ticker)
    except InsufficientDataError:
        bl = compute_thin_baseline(ivs)
        if bl is None:
            return _make_factor("iv_z", current_iv, 0.0)
    z = z_score(current_iv, bl)
    return _make_factor("iv_z", current_iv, z)


def compute_vol_oi_ratio(
    current_volume: int,
    current_oi: int,
    baseline_snapshots: list[OptionsSnapshot],
    ticker: str = "",
) -> FactorScore:
    """Today's volume / yesterday's settled OI vs the 20-day baseline ratio.

    A ratio > 1.0 means more contracts were traded today than exist in
    open positions -- strongly suggests new position opening.
    OI from the API is always prior-day settlement, so this is the
    standard way to detect aggressive new positioning intraday.
    """
    if current_oi <= 0:
        raw_ratio = float(current_volume) if current_volume > 0 else 0.0
    else:
        raw_ratio = float(current_volume) / float(current_oi)

    ratios = extract_vol_oi_ratios(baseline_snapshots)
    if len(ratios) < 5:
        # Conservative fallback: ratio < 1.0 is unremarkable; scale gently above 1.0.
        # A ratio of 1.5 → z≈1.3, ratio of 3.0 → z≈3.3, ratio of 4.25 → z=5.0 (cap).
        z = max(0.0, (raw_ratio - 0.5) / 0.75) if raw_ratio > 0.5 else 0.0
        return _make_factor("vol_oi_z", raw_ratio, z)

    bl = compute_baseline(ratios, ticker=ticker)
    z = z_score(raw_ratio, bl)
    return _make_factor("vol_oi_z", raw_ratio, z)


def compute_sweep_proxy(
    current_volume: int,
    baseline_snapshots: list[OptionsSnapshot],
    ticker: str = "",
) -> FactorScore:
    """Volume-extremity proxy for sweep order detection.

    True sweep detection requires trade-level condition codes and
    multi-exchange fill clustering, which we don't ingest.  As a proxy,
    this factor contributes positively only when volume exceeds 2 sigma
    above the baseline mean — indicating the kind of aggressive, urgent
    execution pattern characteristic of sweep orders.
    """
    volumes = extract_volumes(baseline_snapshots)
    if len(volumes) < BASELINE_MIN_DATAPOINTS:
        return _make_factor("sweep_z", float(current_volume), 0.0)

    bl = compute_baseline(volumes, ticker=ticker)
    raw_z = z_score(float(current_volume), bl)
    z = max(0.0, raw_z - 2.0)
    return _make_factor("sweep_z", float(current_volume), z)


# ---------------------------------------------------------------------------
# Tier 2 -- Medium signal
# ---------------------------------------------------------------------------

def compute_oi_change(
    current_oi: int,
    baseline_snapshots: list[OptionsSnapshot],
    ticker: str = "",
) -> FactorScore:
    """Day-over-day open interest delta vs 20-day average delta.

    Note: OI is always the prior-day settlement figure, so this factor
    reflects yesterday's positioning change, not today's. It is a valid
    but lagging signal, complemented by the real-time vol/OI ratio.
    """
    ois = extract_open_interest(baseline_snapshots)
    if len(ois) < 2:
        return _make_factor("oi_z", float(current_oi), 0.0)

    deltas = [ois[i] - ois[i + 1] for i in range(len(ois) - 1)]
    prev_oi = ois[0] if ois else float(current_oi)
    current_delta = float(current_oi) - prev_oi

    bl = compute_baseline(deltas, ticker=ticker)
    z = z_score(current_delta, bl)
    return _make_factor("oi_z", current_delta, z)


def compute_delta_concentration(
    chain_snapshots: list[OptionsSnapshot],
    underlying_price: float,
    otm_frac_history: list[float] | None = None,
) -> FactorScore:
    """Fraction of chain volume in deep-OTM contracts using delta.

    Uses |delta| < 0.20 to identify deep-OTM contracts (more accurate
    than a raw strike/underlying comparison). Falls back to the price-based
    method for contracts where greeks are unavailable.

    When *otm_frac_history* is provided with sufficient data points,
    the z-score is computed against the rolling baseline. Otherwise,
    falls back to a static assumption (mean=0.15, std=0.10).
    """
    total_vol = 0
    deep_otm_vol = 0

    for snap in chain_snapshots:
        vol = snap.volume or 0
        if vol == 0:
            continue
        total_vol += vol

        if snap.delta is not None:
            if abs(float(snap.delta)) < 0.20:
                deep_otm_vol += vol
        else:
            strike = float(snap.strike_price)
            is_call = snap.contract_type.lower() == "call"
            if is_call and strike > underlying_price * 1.10:
                deep_otm_vol += vol
            elif not is_call and strike < underlying_price * 0.90:
                deep_otm_vol += vol

    if total_vol == 0:
        return _make_factor("delta_conc_z", 0.0, 0.0)

    otm_frac = deep_otm_vol / total_vol

    if otm_frac_history and len(otm_frac_history) >= BASELINE_MIN_DATAPOINTS:
        bl = compute_baseline(otm_frac_history)
        z = z_score(otm_frac, bl)
    else:
        z = (otm_frac - 0.15) / max(0.10, STD_FLOOR)

    return _make_factor("delta_conc_z", otm_frac, z)


def compute_chain_volume(
    chain_snapshots: list[OptionsSnapshot],
    chain_volume_history: list[float],
    ticker: str = "",
) -> FactorScore:
    """Total chain volume vs 20-day baseline for the same underlying.

    Contextualises per-contract anomalies: if the entire chain is quiet
    (z < ~1), a single contract spike is more likely noise.  When the
    whole chain is active, individual spikes carry more conviction.
    """
    from src.config.constants import BASELINE_MIN_DATAPOINTS

    current_total = sum(s.volume or 0 for s in chain_snapshots)

    if not chain_volume_history or len(chain_volume_history) < BASELINE_MIN_DATAPOINTS:
        return _make_factor("chain_vol_z", float(current_total), 0.0)

    bl = compute_baseline(chain_volume_history, ticker=ticker)
    z = z_score(float(current_total), bl)
    return _make_factor("chain_vol_z", float(current_total), z)


def compute_time_to_expiry(
    expiration_date: date,
    current_date: date,
) -> FactorScore:
    """Shorter DTE = stronger signal. < 14 DTE yields positive z-score."""
    dte = max((expiration_date - current_date).days, 0)
    z = (14.0 - dte) / 7.0
    return _make_factor("tte_z", float(dte), z)


# ---------------------------------------------------------------------------
# Tier 3 -- Supporting signals
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
    z = -z_score(current_spread, bl)
    return _make_factor("spread_z", current_spread, z)


def compute_underlying_move(
    underlying_change_pct: float,
    contract_type: str,
    underlying_daily_std: float | None = None,
) -> FactorScore:
    """Stock move correlated with options bet direction.

    Positive contribution when stock moves in the same direction as
    the bet (calls + stock up, puts + stock down).

    When *underlying_daily_std* (the stock's 20-day realized volatility
    of daily percentage changes) is available, the move is normalized by
    it so that a 1% move on a low-vol utility stock scores higher than
    a 1% move on a high-vol tech stock.  Falls back to a flat divisor
    of 1.0 when history is insufficient.
    """
    is_call = contract_type.lower() == "call"
    directional = underlying_change_pct if is_call else -underlying_change_pct
    # Floor at 0.5 to prevent extreme z-scores on near-zero vol stocks.
    # Uses max() rather than an if/else to avoid a discontinuity at the threshold.
    if underlying_daily_std is not None and underlying_daily_std > 0:
        divisor = max(underlying_daily_std, 0.5)
    else:
        divisor = 1.0
    z = directional / divisor
    return _make_factor("underlying_z", underlying_change_pct, z)


def compute_earnings_proximity(
    days_to_earnings: int | None,
) -> FactorScore:
    """Dampen the composite score when a ticker is near an earnings date.

    Options volume naturally spikes 1-2 weeks before earnings. This
    factor applies a negative contribution to avoid flagging expected
    pre-earnings activity as anomalous.

    Penalty schedule (linear ramp):
        Earnings in 0 days  -> z = -3.5  (strong dampening)
        Earnings in 7 days  -> z = -1.75
        Earnings in 14 days -> z = 0.0   (no dampening)
        No earnings nearby  -> z = 0.0
    """
    EARNINGS_WINDOW_DAYS = 14

    if days_to_earnings is None:
        return _make_factor("earnings_z", 0.0, 0.0)

    abs_days = abs(days_to_earnings)

    if days_to_earnings >= 0 and days_to_earnings <= EARNINGS_WINDOW_DAYS:
        z = -(EARNINGS_WINDOW_DAYS - days_to_earnings) / 4.0
    elif days_to_earnings < 0 and abs_days <= 3:
        z = -(3 - abs_days) / 3.0
    else:
        z = 0.0

    return _make_factor("earnings_z", float(days_to_earnings), z)
