"""Quick smoke test — verify DB connection, Polygon API, and email config."""

import asyncio
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
logger = logging.getLogger(__name__)


async def main() -> None:
    from sqlalchemy import text

    from src.config.settings import get_settings
    from src.database.engine import dispose_engine, get_engine
    from src.ingestion.client import close_client, polygon_get

    settings = get_settings()

    # 1. Database
    logger.info("--- Database ---")
    engine = get_engine()
    async with engine.connect() as conn:
        row = await conn.execute(text("SELECT count(*) FROM stock_snapshots"))
        logger.info("  DB connected OK — stock_snapshots has %d rows", row.scalar())

    # 2. Polygon API — market status
    logger.info("--- Polygon API ---")
    data = await polygon_get("/v1/marketstatus/now")
    logger.info("  Market status: %s", data.get("market", "unknown"))

    # 3. Polygon API — stock snapshot
    data2 = await polygon_get("/v2/snapshot/locale/us/markets/stocks/tickers", params={"tickers": "AAPL"})
    tickers = data2.get("tickers", [])
    if tickers:
        aapl = tickers[0]
        day = aapl.get("day", {})
        logger.info("  AAPL snapshot: close=$%.2f volume=%s", day.get("c", 0), day.get("v", 0))
    else:
        logger.info("  No stock snapshot data (market may be closed)")

    # 4. Polygon API — option chain (small test)
    data3 = await polygon_get("/v3/snapshot/options/AAPL", params={"limit": 5})
    results = data3.get("results", [])
    logger.info("  AAPL option chain sample: %d contracts returned", len(results))
    if results:
        d = results[0].get("details", {})
        logger.info("  First contract: %s", d.get("ticker", "?"))

    # 5. Email config
    logger.info("--- Email Config ---")
    logger.info("  Sender: %s", settings.sender_email)
    logger.info("  Recipient: %s", settings.recipient_email)
    logger.info("  Email enabled: %s", settings.anomaly_email_enabled)
    logger.info("  Alert threshold: %.1f", settings.anomaly_alert_min_score)

    logger.info("\n=== All systems go ===")

    await close_client()
    await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
