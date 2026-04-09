"""Composite score computation -- aggregate factors into a 0-10 score."""

import logging
from datetime import date, datetime

from src.config.constants import BASELINE_LOOKBACK_DAYS, COMPOSITE_SCORE_MAX, FACTOR_WEIGHT_MAP
from src.config.settings import get_settings
from src.database.models import OptionsSnapshot
from src.exceptions import InsufficientDataError
from src.scoring.factors import (
    compute_chain_volume,
    compute_delta_concentration,
    compute_earnings_proximity,
    compute_iv_spike,
    compute_oi_change,
    compute_premium_surge,
    compute_spread,
    compute_time_to_expiry,
    compute_underlying_move,
    compute_vol_oi_ratio,
    compute_volume_spike,
)
from src.scoring.gate import check_already_priced_in
from src.scoring.models import FactorScore, ScoreBreakdown

logger = logging.getLogger(__name__)


def _zero_factor(key: str, raw: float = 0.0) -> FactorScore:
    """Return a neutral FactorScore using the canonical weight from FACTOR_WEIGHT_MAP."""
    return FactorScore(raw=raw, z_score=0.0, weight=FACTOR_WEIGHT_MAP.get(key, 0.0), contribution=0.0)


def score_contract(
    current: OptionsSnapshot,
    baseline_snapshots: list[OptionsSnapshot],
    chain_snapshots: list[OptionsSnapshot],
    underlying_price: float,
    underlying_change_pct: float,
    snap_date: date,
    days_to_earnings: int | None = None,
    chain_volume_history: list[float] | None = None,
) -> ScoreBreakdown:
    """Compute the full composite score for a single option contract.

    Returns a ScoreBreakdown regardless of whether the alert threshold
    is met -- the caller decides whether to act on it.
    """
    settings = get_settings()
    ticker = current.underlying_ticker
    contract = current.option_ticker
    contract_type = current.contract_type

    current_volume = current.volume or 0
    current_oi = current.open_interest or 0
    current_close = float(current.close) if current.close is not None else 0.0
    current_bid = float(current.bid) if current.bid is not None else None
    current_ask = float(current.ask) if current.ask is not None else None
    current_iv = float(current.implied_volatility) if current.implied_volatility is not None else 0.0

    factors: dict[str, FactorScore] = {}

    # --- Tier 1: primary volume/flow signals ---
    try:
        factors["vol_z"] = compute_volume_spike(current_volume, baseline_snapshots, ticker=contract)
    except InsufficientDataError:
        factors["vol_z"] = _zero_factor("vol_z", raw=float(current_volume))

    try:
        factors["prem_z"] = compute_premium_surge(current_close, current_volume, baseline_snapshots, ticker=contract)
    except InsufficientDataError:
        factors["prem_z"] = _zero_factor("prem_z", raw=current_close * current_volume * 100)

    try:
        factors["iv_z"] = compute_iv_spike(current_iv, baseline_snapshots, ticker=contract)
    except InsufficientDataError:
        factors["iv_z"] = _zero_factor("iv_z", raw=current_iv)

    try:
        factors["vol_oi_z"] = compute_vol_oi_ratio(current_volume, current_oi, baseline_snapshots, ticker=contract)
    except InsufficientDataError:
        factors["vol_oi_z"] = _zero_factor("vol_oi_z")

    # --- Tier 2: structural positioning ---
    factors["chain_vol_z"] = compute_chain_volume(
        chain_snapshots, chain_volume_history or [], ticker=ticker,
    )

    factors["delta_conc_z"] = compute_delta_concentration(chain_snapshots, underlying_price)

    try:
        factors["oi_z"] = compute_oi_change(current_oi, baseline_snapshots, ticker=contract)
    except InsufficientDataError:
        factors["oi_z"] = _zero_factor("oi_z", raw=float(current_oi))

    factors["earnings_z"] = compute_earnings_proximity(days_to_earnings)

    exp_date = current.expiration_date
    factors["tte_z"] = compute_time_to_expiry(exp_date, snap_date)

    # --- Tier 3: supporting context ---
    try:
        factors["spread_z"] = compute_spread(current_bid, current_ask, baseline_snapshots, ticker=contract)
    except InsufficientDataError:
        factors["spread_z"] = _zero_factor("spread_z")

    factors["underlying_z"] = compute_underlying_move(underlying_change_pct, contract_type)

    # Weighted sum -> dampen by baseline confidence -> normalise to 0-10
    raw_composite = sum(f.contribution for f in factors.values())

    # Thin baselines produce unreliable z-scores.  Dampen the composite
    # proportionally: 5 data points → 0.625× multiplier, 20 → 1.0×.
    baseline_n = len(baseline_snapshots)
    confidence = min(1.0, 0.5 + 0.5 * baseline_n / BASELINE_LOOKBACK_DAYS)
    raw_composite *= confidence

    normalized = min(COMPOSITE_SCORE_MAX, max(0.0, raw_composite * 2.0))

    priced_in = check_already_priced_in(contract_type, underlying_change_pct)
    triggered = normalized >= settings.anomaly_alert_min_score and not priced_in

    breakdown = ScoreBreakdown(
        ticker=ticker,
        contract=contract,
        composite_score=round(normalized, 3),
        factors=factors,
        underlying_move_pct=underlying_change_pct,
        already_priced_in=priced_in,
        timestamp=datetime.utcnow(),
        triggered=triggered,
        underlying_price=underlying_price,
        option_price=current_close,
        option_volume=current_volume,
        open_interest=current_oi,
        contract_type=contract_type,
        expiration_date=str(exp_date),
        strike_price=float(current.strike_price),
    )

    if triggered:
        logger.info(
            "TRIGGERED %s | composite=%.2f priced_in=%s earnings=%s",
            contract, normalized, priced_in, days_to_earnings,
        )
    else:
        logger.debug(
            "scored %s | composite=%.2f triggered=%s priced_in=%s",
            contract, normalized, triggered, priced_in,
        )

    return breakdown
