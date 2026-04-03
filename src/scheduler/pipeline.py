"""Single scan cycle -- the core pipeline executed once per loop iteration."""

import logging
import time
from datetime import date

from src.alerts.dedup import log_alert_result, should_send_alert
from src.alerts.formatter import format_alert_email
from src.alerts.sender import send_email
from src.database.engine import get_session_factory
from src.database.repositories.options_snapshot_repo import OptionsSnapshotRepo
from src.database.repositories.scoring_repo import ScoringRepo
from src.exceptions import AlertError, OptionFinderError
from src.ingestion.earnings import days_until_earnings, fetch_next_earnings_date
from src.ingestion.market_status import is_market_open
from src.ingestion.news import fetch_ticker_news
from src.ingestion.option_snapshots import ingest_option_chain
from src.ingestion.stock_snapshots import get_large_movers, ingest_stock_snapshots
from src.scoring.composite import score_contract
from src.scoring.models import ScoreBreakdown

logger = logging.getLogger(__name__)

MIN_VOLUME_THRESHOLD = 10
SCORING_BATCH_SIZE = 200


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
        "errors": 0,
    }
    t0 = time.monotonic()
    snap_date = date.today()
    factory = get_session_factory()

    # 1. Check market status
    try:
        if not await is_market_open():
            logger.info("market is closed — skipping scan cycle")
            stats["duration_s"] = time.monotonic() - t0
            return stats
    except OptionFinderError:
        logger.warning("could not check market status — proceeding anyway")

    # 2. Fetch stock snapshots
    async with factory() as session:
        try:
            stock_snaps = await ingest_stock_snapshots(session, snap_date)
            stats["stocks_fetched"] = len(stock_snaps)
        except OptionFinderError:
            logger.exception("failed to fetch stock snapshots")
            stats["errors"] += 1
            stats["duration_s"] = time.monotonic() - t0
            return stats

    large_movers = get_large_movers(stock_snaps)
    underlying_change: dict[str, float] = {
        s.ticker: float(s.todaysChangePerc) if s.todaysChangePerc is not None else 0.0
        for s in stock_snaps
    }

    # 3. Build list of underlyings to scan
    underlyings = [s.ticker for s in stock_snaps if s.day and s.day.v and s.day.v > 0]
    logger.info(
        "scanning option chains for %d underlyings (%d large movers)",
        len(underlyings),
        len(large_movers),
    )

    # 4. For each underlying: fetch chain, score, persist, alert
    for underlying in underlyings:
        stats["underlyings_scanned"] += 1
        try:
            async with factory() as session:
                chain = await ingest_option_chain(session, underlying, snap_date)
                if not chain:
                    continue

                opt_repo = OptionsSnapshotRepo(session)
                scoring_repo = ScoringRepo(session)
                chain_db = await opt_repo.get_by_underlying_date(underlying, snap_date)
                u_price_raw = chain[0].underlying_asset.price if chain[0].underlying_asset else None
                u_price = float(u_price_raw) if u_price_raw is not None else 0.0
                u_change = underlying_change.get(underlying, 0.0)

                earnings_date = await fetch_next_earnings_date(underlying, as_of=snap_date)
                dte = days_until_earnings(earnings_date, as_of=snap_date)

                score_rows: list[dict] = []
                triggered_breakdowns: list[ScoreBreakdown] = []

                for snap_model in chain_db:
                    if (snap_model.volume or 0) < MIN_VOLUME_THRESHOLD:
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
                            days_to_earnings=dte,
                        )
                        stats["contracts_scored"] += 1
                        score_rows.append(_breakdown_to_row(breakdown, snap_date))

                        if breakdown.triggered:
                            triggered_breakdowns.append(breakdown)

                    except Exception:
                        logger.debug("scoring error for %s", snap_model.option_ticker, exc_info=True)
                        stats["errors"] += 1
                        continue

                    if len(score_rows) >= SCORING_BATCH_SIZE:
                        await scoring_repo.save_many(score_rows)
                        stats["scores_persisted"] += len(score_rows)
                        score_rows.clear()

                # Flush remaining scores
                if score_rows:
                    await scoring_repo.save_many(score_rows)
                    stats["scores_persisted"] += len(score_rows)
                    score_rows.clear()

                await session.commit()

                # Process alerts for triggered contracts
                for breakdown in triggered_breakdowns:
                    try:
                        should_send, is_update = await should_send_alert(
                            session, breakdown, snap_date
                        )
                        if not should_send:
                            stats["alerts_suppressed"] += 1
                            continue

                        news = await fetch_ticker_news(underlying, limit=5)
                        msg = format_alert_email(breakdown, news=news, is_update=is_update)

                        try:
                            actually_sent = send_email(msg)
                            if actually_sent:
                                await log_alert_result(session, breakdown, snap_date, "sent", msg["Subject"])
                                stats["alerts_fired"] += 1
                            else:
                                await log_alert_result(session, breakdown, snap_date, "suppressed", msg["Subject"])
                                stats["alerts_skipped_email_off"] += 1
                        except AlertError:
                            await log_alert_result(session, breakdown, snap_date, "failed", msg["Subject"])
                            stats["errors"] += 1

                    except Exception:
                        logger.exception("alert pipeline error for %s", breakdown.contract)
                        stats["errors"] += 1

        except OptionFinderError:
            logger.exception("failed to process %s", underlying)
            stats["errors"] += 1
        except Exception:
            logger.exception("unexpected error processing %s", underlying)
            stats["errors"] += 1

    stats["duration_s"] = round(time.monotonic() - t0, 2)
    logger.info(
        "scan cycle complete in %.1fs — stocks=%d underlyings=%d scored=%d "
        "persisted=%d alerts_fired=%d suppressed=%d email_off=%d errors=%d",
        stats["duration_s"],
        stats["stocks_fetched"],
        stats["underlyings_scanned"],
        stats["contracts_scored"],
        stats["scores_persisted"],
        stats["alerts_fired"],
        stats["alerts_suppressed"],
        stats["alerts_skipped_email_off"],
        stats["errors"],
    )
    return stats
