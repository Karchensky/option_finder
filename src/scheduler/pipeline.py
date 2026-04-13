"""Single scan cycle -- the core pipeline executed once per loop iteration."""

import asyncio
import logging
import re
import statistics
import time
from datetime import date, datetime, timezone

from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from src.alerts.dedup import log_alert_result, retry_failed_alerts, should_send_alert
from src.alerts.formatter import format_digest_email
from src.alerts.sender import send_email
from src.config.constants import BASELINE_MIN_DATAPOINTS, EASTERN, MIN_PREMIUM_THRESHOLD, TRIGGER_CONFIRM_SCANS
from src.database.engine import get_session_factory
from src.database.repositories.alert_repo import AlertRepo
from src.database.repositories.options_snapshot_repo import OptionsSnapshotRepo
from src.database.repositories.scoring_repo import ScoringRepo
from src.database.repositories.stock_snapshot_repo import StockSnapshotRepo
from src.database.repositories.trigger_candidate_repo import TriggerCandidateRepo
from src.exceptions import AlertError, OptionFinderError, PolygonAPIError
from src.ingestion.earnings import days_until_earnings, fetch_next_earnings_date
from src.ingestion.market_status import is_market_open
from src.ingestion.news import fetch_ticker_news
from src.ingestion.option_snapshots import ingest_option_chain
from src.ingestion.schemas import StockTickerSnapshot
from src.ingestion.stock_snapshots import get_large_movers, ingest_stock_snapshots
from src.scoring.composite import score_contract
from src.scoring.models import FactorScore, ScoreBreakdown

logger = logging.getLogger(__name__)

MIN_VOLUME_THRESHOLD = 100
SCORING_BATCH_SIZE = 200

# Concurrency: how many option chains to fetch in parallel
API_CONCURRENCY = 15

# Only tickers matching this regex are scanned (plain common stocks, 1-5 uppercase letters).
# Skips preferred shares (PRApB), warrants (.WS), units, etc.
_COMMON_TICKER_RE = re.compile(r"^[A-Z]{1,5}$")


def _is_scannable_ticker(snap: StockTickerSnapshot) -> bool:
    """Return True if this stock ticker is worth scanning for option chains.

    Uses ticker format only -- NOT intraday volume, which is 0 near market open.
    Previous-day volume is checked if available to skip dormant tickers.
    """
    if not _COMMON_TICKER_RE.match(snap.ticker):
        return False
    if snap.prev_day and snap.prev_day.v is not None and snap.prev_day.v < 1000:
        return False
    return True


def _breakdown_to_row(b: ScoreBreakdown, snap_date: date) -> dict:
    """Convert a ScoreBreakdown into a dict for ScoringRepo.save_many()."""
    return {
        "option_ticker": b.contract,
        "underlying_ticker": b.ticker,
        "snap_date": snap_date,
        "composite_score": round(b.composite_score, 3),
        "factors": b.factors_to_dict(),
        "underlying_move_pct": round(b.underlying_move_pct, 4) if b.underlying_move_pct else 0.0,
        "already_priced_in": b.already_priced_in,
        "triggered": b.triggered,
    }


async def _process_underlying(
    underlying: str,
    snap_date: date,
    u_change: float,
    u_price_fallback: float,
    factory: async_sessionmaker[AsyncSession],
    semaphore: asyncio.Semaphore,
) -> dict:
    """Fetch chain, score contracts, persist results for ONE underlying.

    Runs under the semaphore to limit concurrent API calls.
    Returns a stats dict and list of triggered breakdowns.
    """
    local_stats = {
        "contracts_scored": 0,
        "scores_persisted": 0,
        "alerts_suppressed": 0,
        "errors": 0,
        "triggered": [],
    }

    async with semaphore:
        try:
            async with factory() as session:
                chain = await ingest_option_chain(session, underlying, snap_date)
                if not chain:
                    return local_stats

                opt_repo = OptionsSnapshotRepo(session)
                scoring_repo = ScoringRepo(session)
                chain_db = await opt_repo.get_by_underlying_date(underlying, snap_date)
                u_price_raw = chain[0].underlying_asset.price if chain[0].underlying_asset else None
                u_price = float(u_price_raw) if u_price_raw is not None else u_price_fallback

                chain_vol_history = await opt_repo.get_chain_volume_history(underlying, snap_date)
                otm_frac_history = await opt_repo.get_otm_fraction_history(underlying, snap_date)

                # Compute realized vol for underlying_z normalization (once per underlying)
                stock_repo = StockSnapshotRepo(session)
                change_history = await stock_repo.get_change_pct_history(underlying, snap_date)
                u_daily_std: float | None = None
                if len(change_history) >= BASELINE_MIN_DATAPOINTS:
                    u_daily_std = statistics.pstdev(change_history)

                dte_earnings: int | None = None
                try:
                    earnings_date = await fetch_next_earnings_date(underlying, as_of=snap_date)
                    dte_earnings = days_until_earnings(earnings_date, as_of=snap_date)
                except PolygonAPIError:
                    logger.debug("earnings lookup failed for %s — scoring without dampener", underlying)

                score_rows: list[dict] = []

                for snap_model in chain_db:
                    snap_vol = snap_model.volume or 0
                    if snap_vol < MIN_VOLUME_THRESHOLD:
                        continue
                    snap_price = float(snap_model.close) if snap_model.close is not None else 0.0
                    snap_premium = snap_price * snap_vol * 100
                    if snap_premium < MIN_PREMIUM_THRESHOLD:
                        continue

                    try:
                        baseline = await opt_repo.get_baseline(
                            snap_model.option_ticker, snap_date
                        )
                        breakdown = score_contract(
                            current=snap_model,
                            baseline_snapshots=baseline,
                            chain_snapshots=chain_db,
                            underlying_price=u_price,
                            underlying_change_pct=u_change,
                            snap_date=snap_date,
                            days_to_earnings=dte_earnings,
                            chain_volume_history=chain_vol_history,
                            otm_frac_history=otm_frac_history,
                            underlying_daily_std=u_daily_std,
                        )
                        local_stats["contracts_scored"] += 1
                        score_rows.append(_breakdown_to_row(breakdown, snap_date))

                        if breakdown.triggered:
                            local_stats["triggered"].append(breakdown)

                    except Exception:
                        logger.debug("scoring error for %s", snap_model.option_ticker, exc_info=True)
                        local_stats["errors"] += 1
                        continue

                    if len(score_rows) >= SCORING_BATCH_SIZE:
                        await scoring_repo.save_many(score_rows)
                        local_stats["scores_persisted"] += len(score_rows)
                        score_rows.clear()

                if score_rows:
                    await scoring_repo.save_many(score_rows)
                    local_stats["scores_persisted"] += len(score_rows)
                    score_rows.clear()

                await session.commit()

                n_triggered = len(local_stats["triggered"])
                if n_triggered:
                    logger.info(
                        "%s: scored %d contracts, %d triggered",
                        underlying, local_stats["contracts_scored"], n_triggered,
                    )

        except OptionFinderError:
            logger.exception("failed to process %s", underlying)
            local_stats["errors"] += 1
        except Exception:
            logger.exception("unexpected error processing %s", underlying)
            local_stats["errors"] += 1

    return local_stats


def _reconstruct_breakdown(
    scoring: "ScoringResult",
    snap: "OptionsSnapshot | None",
) -> ScoreBreakdown:
    """Reconstruct a ScoreBreakdown from persisted scoring + snapshot data for retry."""
    factors: dict[str, FactorScore] = {}
    for key, fdata in (scoring.factors or {}).items():
        factors[key] = FactorScore(
            raw=fdata.get("raw", 0.0),
            z_score=fdata.get("z_score", 0.0),
            weight=fdata.get("weight", 0.0),
            contribution=fdata.get("contribution", 0.0),
        )

    return ScoreBreakdown(
        ticker=scoring.underlying_ticker,
        contract=scoring.option_ticker,
        composite_score=float(scoring.composite_score),
        factors=factors,
        underlying_move_pct=float(scoring.underlying_move_pct or 0),
        already_priced_in=scoring.already_priced_in,
        timestamp=datetime.now(timezone.utc),
        triggered=scoring.triggered,
        underlying_price=float(snap.underlying_price) if snap and snap.underlying_price else None,
        option_price=float(snap.close) if snap and snap.close else None,
        option_volume=snap.volume if snap else None,
        open_interest=snap.open_interest if snap else None,
        contract_type=snap.contract_type if snap else "",
        expiration_date=str(snap.expiration_date) if snap else "",
        strike_price=float(snap.strike_price) if snap else None,
    )


async def _retry_failed_alerts(
    factory: async_sessionmaker[AsyncSession],
    snap_date: date,
) -> int:
    """Retry sending alerts that failed in earlier scan cycles today.

    Returns the number of alerts successfully retried.
    """
    async with factory() as session:
        failed = await retry_failed_alerts(session, snap_date)
        if not failed:
            return 0

        logger.info("found %d failed alerts eligible for retry", len(failed))

        scoring_repo = ScoringRepo(session)
        opt_repo = OptionsSnapshotRepo(session)
        alert_repo = AlertRepo(session)
        breakdowns: list[ScoreBreakdown] = []
        alert_ids: list[int] = []

        for alert in failed:
            scoring = await scoring_repo.get_by_option_ticker_date(
                alert.option_ticker, snap_date,
            )
            if scoring is None:
                logger.debug("no scoring result for retry of %s — skipping", alert.option_ticker)
                continue
            snap = await opt_repo.get_by_option_ticker_date(alert.option_ticker, snap_date)
            breakdowns.append(_reconstruct_breakdown(scoring, snap))
            alert_ids.append(alert.id)

        if not breakdowns:
            return 0

        msg = format_digest_email(breakdowns)
        msg.replace_header("Subject", f"RETRY: {msg['Subject']}")

        try:
            sent = send_email(msg)
            if sent:
                for aid in alert_ids:
                    await alert_repo.mark_sent(aid)
                await session.commit()
                logger.info("successfully retried %d failed alerts", len(breakdowns))
                return len(breakdowns)
            return 0
        except AlertError:
            logger.exception("retry attempt also failed — incrementing retry counts")
            for aid in alert_ids:
                await alert_repo.increment_retry_count(aid)
            await session.commit()
            return 0


async def run_scan_cycle() -> dict:
    """Execute one full scan cycle and return stats."""
    stats = {
        "duration_s": 0.0,
        "stocks_fetched": 0,
        "underlyings_scanned": 0,
        "contracts_scored": 0,
        "scores_persisted": 0,
        "alerts_fired": 0,
        "alerts_suppressed": 0,
        "alerts_skipped_email_off": 0,
        "alerts_retried": 0,
        "errors": 0,
    }
    t0 = time.monotonic()
    snap_date = datetime.now(EASTERN).date()
    factory = get_session_factory()

    # 1. Check market status
    try:
        if not await is_market_open():
            logger.info("market is closed — skipping scan cycle")
            stats["duration_s"] = time.monotonic() - t0
            return stats
    except OptionFinderError:
        logger.warning("could not check market status — proceeding anyway")

    # 2. Fetch stock snapshots (single bulk API call)
    async with factory() as session:
        try:
            stock_snaps = await ingest_stock_snapshots(session, snap_date)
            stats["stocks_fetched"] = len(stock_snaps)
        except OptionFinderError:
            logger.exception("failed to fetch stock snapshots")
            stats["errors"] += 1
            stats["duration_s"] = time.monotonic() - t0
            return stats

    underlying_change: dict[str, float] = {
        s.ticker: float(s.todaysChangePerc) if s.todaysChangePerc is not None else 0.0
        for s in stock_snaps
    }
    underlying_price: dict[str, float] = {
        s.ticker: float(s.day.c) if s.day and s.day.c is not None else 0.0
        for s in stock_snaps
    }

    # 3. Pre-filter: only common-stock tickers with meaningful volume
    underlyings = [s.ticker for s in stock_snaps if _is_scannable_ticker(s)]
    large_movers = get_large_movers(stock_snaps)
    logger.info(
        "scanning option chains for %d underlyings (filtered from %d stocks, %d large movers) — concurrency=%d",
        len(underlyings),
        len(stock_snaps),
        len(large_movers),
        API_CONCURRENCY,
    )
    stats["underlyings_scanned"] = len(underlyings)

    # 4. Fetch + score underlyings in batches with bounded concurrency
    BATCH_SIZE = 500
    semaphore = asyncio.Semaphore(API_CONCURRENCY)
    all_triggered: list[ScoreBreakdown] = []
    processed = 0

    for batch_start in range(0, len(underlyings), BATCH_SIZE):
        batch = underlyings[batch_start : batch_start + BATCH_SIZE]
        tasks = [
            _process_underlying(
                u, snap_date, underlying_change.get(u, 0.0),
                underlying_price.get(u, 0.0), factory, semaphore,
            )
            for u in batch
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for r in results:
            if isinstance(r, Exception):
                logger.warning("task-level error: %s", r)
                stats["errors"] += 1
                continue
            stats["contracts_scored"] += r["contracts_scored"]
            stats["scores_persisted"] += r["scores_persisted"]
            stats["errors"] += r["errors"]
            all_triggered.extend(r["triggered"])

        processed += len(batch)
        logger.info(
            "progress: %d/%d underlyings processed, %d scored, %d triggered so far",
            processed, len(underlyings), stats["contracts_scored"], len(all_triggered),
        )

    logger.info(
        "scoring complete — %d contracts scored, %d triggered before persistence check",
        stats["contracts_scored"],
        len(all_triggered),
    )

    # 5b. Trigger persistence — require consecutive scans before alerting
    confirmed_breakdowns: list[ScoreBreakdown] = []
    if all_triggered:
        now = datetime.now(timezone.utc)
        triggered_tickers_set: set[str] = {b.contract for b in all_triggered}

        async with factory() as session:
            tc_repo = TriggerCandidateRepo(session)

            expired_count = await tc_repo.expire_stale_candidates(snap_date, triggered_tickers_set)
            if expired_count:
                logger.info("expired %d trigger candidates that did not persist this scan", expired_count)

            for breakdown in all_triggered:
                try:
                    candidate = await tc_repo.upsert_candidate({
                        "option_ticker": breakdown.contract,
                        "underlying_ticker": breakdown.ticker,
                        "alert_date": snap_date,
                        "first_triggered_at": now,
                        "last_triggered_at": now,
                        "trigger_count": 1,
                        "missed_scans": 0,
                        "peak_score": breakdown.composite_score,
                        "peak_factors": breakdown.factors_to_dict(),
                        "confirmed": False,
                        "expired": False,
                    })

                    if candidate.trigger_count >= TRIGGER_CONFIRM_SCANS and not candidate.confirmed:
                        await tc_repo.mark_confirmed(breakdown.contract, snap_date)
                        confirmed_breakdowns.append(breakdown)
                        logger.info(
                            "CONFIRMED %s after %d consecutive scans (score=%.2f)",
                            breakdown.contract, candidate.trigger_count, breakdown.composite_score,
                        )
                    elif candidate.confirmed:
                        confirmed_breakdowns.append(breakdown)
                        logger.debug(
                            "already-confirmed %s re-triggered (score=%.2f) — passing to dedup",
                            breakdown.contract, breakdown.composite_score,
                        )
                    elif candidate.trigger_count < TRIGGER_CONFIRM_SCANS:
                        logger.info(
                            "pending confirmation: %s scan %d/%d (score=%.2f)",
                            breakdown.contract, candidate.trigger_count, TRIGGER_CONFIRM_SCANS,
                            breakdown.composite_score,
                        )
                except Exception:
                    logger.debug("trigger candidate error for %s", breakdown.contract, exc_info=True)
                    stats["errors"] += 1

            await session.commit()

    logger.info(
        "%d triggered → %d confirmed (persistence >= %d scans)",
        len(all_triggered), len(confirmed_breakdowns), TRIGGER_CONFIRM_SCANS,
    )

    # 6. Dedup confirmed triggers
    final_triggered: list[ScoreBreakdown] = []
    if confirmed_breakdowns:
        async with factory() as session:
            for breakdown in confirmed_breakdowns:
                try:
                    should_send, is_update = await should_send_alert(session, breakdown, snap_date)
                    if not should_send:
                        stats["alerts_suppressed"] += 1
                        continue
                    final_triggered.append(breakdown)
                except Exception:
                    logger.debug("dedup error for %s", breakdown.contract, exc_info=True)
                    stats["errors"] += 1

    # 7. Send ONE digest email
    if final_triggered:
        logger.info(
            "scan produced %d triggered alerts after dedup — sending digest email",
            len(final_triggered),
        )
        try:
            tickers_for_news = sorted({b.ticker for b in final_triggered})
            news_by_ticker: dict[str, list] = {}
            for ticker in tickers_for_news[:10]:
                try:
                    news_by_ticker[ticker] = await fetch_ticker_news(ticker, limit=3)
                except PolygonAPIError:
                    logger.debug("news fetch failed for %s", ticker, exc_info=True)

            msg = format_digest_email(final_triggered, news_by_ticker=news_by_ticker)
            try:
                actually_sent = send_email(msg)
                if actually_sent:
                    stats["alerts_fired"] = len(final_triggered)
                    async with factory() as session:
                        for breakdown in final_triggered:
                            await log_alert_result(session, breakdown, snap_date, "sent", msg["Subject"])
                else:
                    stats["alerts_skipped_email_off"] = len(final_triggered)
            except AlertError:
                logger.exception("failed to send digest email")
                stats["errors"] += 1
                async with factory() as session:
                    for breakdown in final_triggered:
                        await log_alert_result(session, breakdown, snap_date, "failed", msg["Subject"])
        except Exception:
            logger.exception("digest email pipeline error")
            stats["errors"] += 1
    else:
        logger.info("scan produced 0 triggered alerts — no email to send")

    # 8. Retry failed alerts from earlier scan cycles today
    try:
        stats["alerts_retried"] = await _retry_failed_alerts(factory, snap_date)
    except Exception:
        logger.exception("alert retry step failed")

    stats["duration_s"] = round(time.monotonic() - t0, 2)
    logger.info(
        "scan cycle complete in %.1fs — stocks=%d underlyings=%d scored=%d "
        "persisted=%d alerts_fired=%d suppressed=%d email_off=%d retried=%d errors=%d",
        stats["duration_s"],
        stats["stocks_fetched"],
        stats["underlyings_scanned"],
        stats["contracts_scored"],
        stats["scores_persisted"],
        stats["alerts_fired"],
        stats["alerts_suppressed"],
        stats["alerts_skipped_email_off"],
        stats["alerts_retried"],
        stats["errors"],
    )
    return stats
