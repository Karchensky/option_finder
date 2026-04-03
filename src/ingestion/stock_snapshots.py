"""Fetch and persist full US stock market snapshots."""

import logging
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from src.database.repositories.stock_snapshot_repo import StockSnapshotRepo
from src.ingestion.client import polygon_get
from src.ingestion.schemas import StockTickerSnapshot

logger = logging.getLogger(__name__)


async def fetch_stock_snapshots() -> list[StockTickerSnapshot]:
    """Fetch a snapshot of every US stock ticker."""
    data = await polygon_get("/v2/snapshot/locale/us/markets/stocks/tickers")
    tickers = data.get("tickers") or []
    snapshots = [StockTickerSnapshot.model_validate(t) for t in tickers]
    logger.info("fetched %d stock snapshots", len(snapshots))
    return snapshots


def snapshot_to_row(snap: StockTickerSnapshot, snap_date: date) -> dict:
    """Convert a Pydantic stock snapshot to a dict suitable for DB upsert."""
    day = snap.day
    return {
        "ticker": snap.ticker,
        "snap_date": snap_date,
        "open": day.o if day else None,
        "high": day.h if day else None,
        "low": day.l if day else None,
        "close": day.c if day else None,
        "volume": day.v if day else None,
        "vwap": day.vw if day else None,
        "change_pct": snap.todaysChangePerc,
        "prev_close": snap.prev_day.c if snap.prev_day else None,
    }


async def ingest_stock_snapshots(session: AsyncSession, snap_date: date) -> list[StockTickerSnapshot]:
    """Fetch and upsert all stock snapshots, returning the parsed list."""
    snapshots = await fetch_stock_snapshots()
    rows = [snapshot_to_row(s, snap_date) for s in snapshots]

    repo = StockSnapshotRepo(session)
    await repo.upsert_many(rows)
    await session.commit()

    logger.info("upserted %d stock snapshots for %s", len(rows), snap_date)
    return snapshots


def get_large_movers(snapshots: list[StockTickerSnapshot], threshold: float = 2.0) -> dict[str, float]:
    """Return a map of ticker -> change_pct for stocks with absolute move > threshold."""
    movers: dict[str, float] = {}
    for snap in snapshots:
        pct = float(snap.todaysChangePerc) if snap.todaysChangePerc is not None else 0.0
        if abs(pct) > threshold:
            movers[snap.ticker] = pct
    return movers
