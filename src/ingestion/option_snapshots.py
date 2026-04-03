"""Fetch and persist option chain snapshots for a given underlying."""

import logging
from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from src.database.repositories.options_snapshot_repo import OptionsSnapshotRepo
from src.ingestion.client import fetch_all_pages
from src.ingestion.schemas import OptionSnapshotResult

logger = logging.getLogger(__name__)


async def fetch_option_chain(underlying: str) -> list[OptionSnapshotResult]:
    """Fetch the full option chain snapshot for *underlying* (paginated)."""
    path = f"/v3/snapshot/options/{underlying}"
    raw_results = await fetch_all_pages(path)
    snapshots = []
    for r in raw_results:
        try:
            snapshots.append(OptionSnapshotResult.model_validate(r))
        except Exception:
            ticker_hint = r.get("details", {}).get("ticker", "?") if isinstance(r, dict) else "?"
            logger.debug("skipping invalid option result for %s: %s", underlying, ticker_hint)
    logger.info("fetched %d option contracts for %s", len(snapshots), underlying)
    return snapshots


def snapshot_to_row(snap: OptionSnapshotResult, snap_date: date) -> dict:
    """Convert a parsed option snapshot into a flat dict for DB upsert."""
    d = snap.details
    day = snap.day
    greeks = snap.greeks
    quote = snap.last_quote
    ua = snap.underlying_asset

    return {
        "option_ticker": d.ticker,
        "underlying_ticker": extract_underlying_ticker(d.ticker),
        "snap_date": snap_date,
        "contract_type": d.contract_type,
        "strike_price": d.strike_price,
        "expiration_date": d.expiration_date,
        "open": day.open if day else None,
        "high": day.high if day else None,
        "low": day.low if day else None,
        "close": day.close if day else None,
        "volume": day.volume if day else None,
        "vwap": day.vwap if day else None,
        "open_interest": snap.open_interest,
        "implied_volatility": snap.implied_volatility,
        "delta": greeks.delta if greeks else None,
        "gamma": greeks.gamma if greeks else None,
        "theta": greeks.theta if greeks else None,
        "vega": greeks.vega if greeks else None,
        "bid": quote.bid if quote else None,
        "ask": quote.ask if quote else None,
        "break_even_price": snap.break_even_price,
        "underlying_price": ua.price if ua else None,
    }


def extract_underlying_ticker(option_ticker: str) -> str:
    """Parse the underlying ticker from a Polygon option ticker.

    Example: 'O:AAPL251219C00150000' -> 'AAPL'
    """
    if ":" not in option_ticker:
        return ""
    body = option_ticker.split(":")[1]
    underlying = ""
    for ch in body:
        if ch.isdigit():
            break
        underlying += ch
    return underlying


async def ingest_option_chain(
    session: AsyncSession,
    underlying: str,
    snap_date: date,
) -> list[OptionSnapshotResult]:
    """Fetch, convert, and upsert the full option chain for *underlying*."""
    snapshots = await fetch_option_chain(underlying)
    if not snapshots:
        return snapshots

    rows = []
    for snap in snapshots:
        row = snapshot_to_row(snap, snap_date)
        row["underlying_ticker"] = underlying
        rows.append(row)

    repo = OptionsSnapshotRepo(session)
    await repo.upsert_many(rows)
    await session.commit()

    logger.info("upserted %d option rows for %s on %s", len(rows), underlying, snap_date)
    return snapshots
