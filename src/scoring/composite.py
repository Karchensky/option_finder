"""Composite score computation — aggregate factors into a 0-10 score."""

import logging
from datetime import date, datetime

from src.config.constants import COMPOSITE_SCORE_MAX
from src.config.settings import get_settings
from src.database.models import OptionsSnapshot
from src.scoring.baseline import compute_baseline, extract_volumes
from src.scoring.factors import (
    compute_oi_change,
    compute_otm_clustering,
    compute_premium_surge,
    compute_spread,
    compute_sweep_detection,
    compute_time_to_expiry,
    compute_underlying_move,
    compute_volume_spike,
)
from src.scoring.gate import check_already_priced_in
from src.scoring.models import FactorScore, ScoreBreakdown

logger = logging.getLogger(__name__)


def score_contract(
    current: OptionsSnapshot,
    baseline_snapshots: list[OptionsSnapshot],
    chain_snapshots: list[OptionsSnapshot],
    underlying_price: float,
    underlying_change_pct: float,
    snap_date: date,
) -> ScoreBreakdown:
    """Compute the full composite score for a single option contract.

    Returns a ScoreBreakdown regardless of whether the alert threshold
    is met — the caller decides whether to act on it.
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

    factors: dict[str, FactorScore] = {}

    try:
        factors["vol_z"] = compute_volume_spike(current_volume, baseline_snapshots, ticker=contract)
    except Exception:
        factors["vol_z"] = FactorScore(raw=float(current_volume), z_score=0.0, weight=0.25, contribution=0.0)

    try:
        factors["prem_z"] = compute_premium_surge(current_close, current_volume, baseline_snapshots, ticker=contract)
    except Exception:
        factors["prem_z"] = FactorScore(raw=current_close * current_volume * 100, z_score=0.0, weight=0.20, contribution=0.0)

    try:
        factors["sweep_z"] = compute_sweep_detection(current_volume, baseline_snapshots, ticker=contract)
    except Exception:
        factors["sweep_z"] = FactorScore(raw=float(current_volume), z_score=0.0, weight=0.15, contribution=0.0)

    try:
        factors["oi_z"] = compute_oi_change(current_oi, baseline_snapshots, ticker=contract)
    except Exception:
        factors["oi_z"] = FactorScore(raw=float(current_oi), z_score=0.0, weight=0.15, contribution=0.0)

    factors["otm_z"] = compute_otm_clustering(chain_snapshots, underlying_price)

    exp_date = current.expiration_date
    factors["tte_z"] = compute_time_to_expiry(exp_date, snap_date)

    try:
        factors["spread_z"] = compute_spread(current_bid, current_ask, baseline_snapshots, ticker=contract)
    except Exception:
        factors["spread_z"] = FactorScore(raw=0.0, z_score=0.0, weight=0.05, contribution=0.0)

    factors["underlying_z"] = compute_underlying_move(underlying_change_pct, contract_type)

    # Weighted sum → normalise to 0-10
    raw_composite = sum(f.contribution for f in factors.values())
    # Scale: empirical tuning; start with 2.0 as the scale factor
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

    logger.info(
        "scored %s | composite=%.2f triggered=%s priced_in=%s",
        contract,
        normalized,
        triggered,
        priced_in,
        extra={"ticker": ticker, "contract": contract, "score": normalized},
    )

    return breakdown
