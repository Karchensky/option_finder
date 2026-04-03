"""Test the scoring pipeline against a single underlying using live API + backfilled data.

Bypasses market-hours check. Exercises: API fetch -> DB upsert -> baseline load -> scoring -> alert formatting.
Does NOT send email (logs what would happen).
"""

import asyncio
import logging
import sys
from datetime import date

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s [%(name)s] %(message)s", stream=sys.stdout)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
logger = logging.getLogger("test_pipeline")


async def main() -> None:
    from src.config.settings import get_settings
    from src.database.engine import get_session_factory, dispose_engine
    from src.database.repositories.options_snapshot_repo import OptionsSnapshotRepo
    from src.ingestion.client import close_client
    from src.ingestion.option_snapshots import ingest_option_chain
    from src.ingestion.news import fetch_ticker_news
    from src.alerts.formatter import format_alert_email
    from src.scoring.composite import score_contract

    settings = get_settings()
    factory = get_session_factory()
    snap_date = date.today()
    test_ticker = "GME"  # smaller chain than AAPL, faster test

    logger.info("=== Pipeline test: %s on %s ===", test_ticker, snap_date)

    # 1. Fetch and ingest option chain
    logger.info("Step 1: Fetching option chain for %s ...", test_ticker)
    async with factory() as session:
        chain = await ingest_option_chain(session, test_ticker, snap_date)
    logger.info("  Fetched %d contracts", len(chain))

    if not chain:
        logger.error("No option chain data — cannot continue")
        return

    # 2. Load from DB and score
    logger.info("Step 2: Loading chain from DB and scoring ...")
    scored = 0
    triggered = 0
    top_scores: list = []

    async with factory() as session:
        opt_repo = OptionsSnapshotRepo(session)
        chain_db = await opt_repo.get_by_underlying_date(test_ticker, snap_date)
        u_price = float(chain[0].underlying_asset.price) if chain[0].underlying_asset and chain[0].underlying_asset.price else 0.0
        logger.info("  %s underlying price: $%.2f", test_ticker, u_price)
        logger.info("  Contracts in DB: %d", len(chain_db))

        for snap in chain_db:
            if (snap.volume or 0) < 10:
                continue

            try:
                baseline = await opt_repo.get_baseline(snap.option_ticker, snap_date)
                breakdown = score_contract(
                    current=snap,
                    baseline_snapshots=baseline,
                    chain_snapshots=chain_db,
                    underlying_price=u_price,
                    underlying_change_pct=0.0,
                    snap_date=snap_date,
                )
                scored += 1

                if breakdown.composite_score >= 5.0:
                    top_scores.append(breakdown)

                if breakdown.triggered:
                    triggered += 1

            except Exception as exc:
                logger.debug("  scoring error: %s", exc)

    logger.info("  Scored: %d contracts", scored)
    logger.info("  Triggered (score >= %.1f): %d", settings.anomaly_alert_min_score, triggered)
    logger.info("  Score >= 5.0: %d", len(top_scores))

    # 3. Show top scores
    top_scores.sort(key=lambda b: -b.composite_score)
    logger.info("\nStep 3: Top 10 scores:")
    for b in top_scores[:10]:
        logger.info(
            "  %s  score=%.2f  vol=%s  type=%s  strike=$%.0f  exp=%s  triggered=%s",
            b.contract, b.composite_score, b.option_volume, b.contract_type,
            b.strike_price or 0, b.expiration_date, b.triggered,
        )
        for k, f in sorted(b.factors.items(), key=lambda kv: -abs(kv[1].contribution)):
            logger.info("    %s: z=%.2f w=%.2f c=%.4f", k, f.z_score, f.weight, f.contribution)

    # 4. Test email formatting (don't send)
    if top_scores:
        logger.info("\nStep 4: Formatting test email for top score ...")
        best = top_scores[0]
        news = await fetch_ticker_news(test_ticker, limit=3)
        msg = format_alert_email(best, news=news)
        logger.info("  Subject: %s", msg["Subject"])
        logger.info("  Would send to: %s", settings.recipient_email)
        logger.info("  Email enabled: %s", settings.anomaly_email_enabled)

    logger.info("\n=== Pipeline test complete ===")

    await close_client()
    await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
