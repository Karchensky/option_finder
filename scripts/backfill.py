"""Backfill historical data from Polygon flat files.

Downloads options day_aggs and stock day_aggs for each trading day in the
lookback window and bulk-inserts them into PostgreSQL. Fields not present
in flat files (OI, greeks, bid/ask) are left NULL — the scoring engine
handles missing baseline data gracefully.

Usage:
    python scripts/backfill.py              # default 30 calendar days
    python scripts/backfill.py --days 45    # custom range
    python scripts/backfill.py --from 2026-03-01 --to 2026-03-31
"""

import argparse
import csv
import gzip
import io
import logging
import re
import sys
import time
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

import asyncio
import boto3
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.config.settings import get_settings
from src.database.engine import get_engine, get_session_factory, dispose_engine
from src.database.models import OptionsSnapshot, StockSnapshot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

BATCH_SIZE = 1000  # asyncpg limit: 32767 params; 22 cols/row → max ~1489 rows

# Regex to parse option ticker: O:AAPL260417C00155000
OPTION_TICKER_RE = re.compile(
    r"^O:([A-Z]+)(\d{6})([CP])(\d{8})$"
)


def _get_s3() -> boto3.client:
    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=settings.polygon_flatfiles_endpoint,
        aws_access_key_id=settings.polygon_s3_access_key,
        aws_secret_access_key=settings.polygon_s3_secret_key,
    )


def _stream_csv(s3, bucket: str, key: str) -> io.StringIO | None:
    """Download and decompress a gzipped CSV from S3, return as StringIO."""
    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
        compressed = obj["Body"].read()
        decompressed = gzip.decompress(compressed)
        return io.StringIO(decompressed.decode("utf-8"))
    except s3.exceptions.NoSuchKey:
        return None
    except Exception as exc:
        logger.warning("  skipping %s: %s", key, exc)
        return None


def _parse_option_ticker(ticker: str) -> dict | None:
    """Parse O:AAPL260417C00155000 into components."""
    m = OPTION_TICKER_RE.match(ticker)
    if not m:
        return None
    underlying, date_str, cp, strike_raw = m.groups()
    try:
        exp_date = datetime.strptime(date_str, "%y%m%d").date()
    except ValueError:
        return None
    contract_type = "call" if cp == "C" else "put"
    strike = Decimal(strike_raw) / 1000
    return {
        "underlying_ticker": underlying,
        "expiration_date": exp_date,
        "contract_type": contract_type,
        "strike_price": strike,
    }


def _safe_decimal(val: str) -> Decimal | None:
    if not val:
        return None
    try:
        return Decimal(val)
    except InvalidOperation:
        return None


def _safe_int(val: str) -> int | None:
    if not val:
        return None
    try:
        return int(float(val))
    except (ValueError, OverflowError):
        return None


def _trading_days(start: date, end: date) -> list[date]:
    """Return all weekdays between start and end (inclusive)."""
    days = []
    current = start
    while current <= end:
        if current.weekday() < 5:  # Mon-Fri
            days.append(current)
        current += timedelta(days=1)
    return days


async def backfill_options_day(s3, snap_date: date, bucket: str) -> int:
    """Load one day of options flat file data into the database."""
    ds = snap_date.isoformat()
    year, month = ds[:4], ds[5:7]
    key = f"us_options_opra/day_aggs_v1/{year}/{month}/{ds}.csv.gz"

    buf = _stream_csv(s3, bucket, key)
    if buf is None:
        logger.info("  [options] %s — no file (holiday/weekend?)", ds)
        return 0

    reader = csv.DictReader(buf)
    rows: list[dict] = []
    skipped = 0

    for raw in reader:
        ticker = raw.get("ticker", "")
        parsed = _parse_option_ticker(ticker)
        if parsed is None:
            skipped += 1
            continue

        volume = _safe_int(raw.get("volume", ""))
        if volume is None or volume == 0:
            continue

        rows.append({
            "option_ticker": ticker,
            "underlying_ticker": parsed["underlying_ticker"],
            "snap_date": snap_date,
            "contract_type": parsed["contract_type"],
            "strike_price": parsed["strike_price"],
            "expiration_date": parsed["expiration_date"],
            "open": _safe_decimal(raw.get("open")),
            "high": _safe_decimal(raw.get("high")),
            "low": _safe_decimal(raw.get("low")),
            "close": _safe_decimal(raw.get("close")),
            "volume": volume,
            "vwap": None,
            "open_interest": None,
            "implied_volatility": None,
            "delta": None,
            "gamma": None,
            "theta": None,
            "vega": None,
            "bid": None,
            "ask": None,
            "break_even_price": None,
            "underlying_price": None,
        })

    if not rows:
        logger.info("  [options] %s — 0 rows with volume (skipped %d)", ds, skipped)
        return 0

    factory = get_session_factory()
    total = 0
    async with factory() as session:
        for i in range(0, len(rows), BATCH_SIZE):
            batch = rows[i : i + BATCH_SIZE]
            stmt = pg_insert(OptionsSnapshot).values(batch)
            update_cols = {
                c.name: c
                for c in stmt.excluded
                if c.name not in ("id", "option_ticker", "snap_date", "created_at")
            }
            stmt = stmt.on_conflict_do_update(
                index_elements=["option_ticker", "snap_date"],
                set_=update_cols,
            )
            await session.execute(stmt)
            total += len(batch)
        await session.commit()

    logger.info("  [options] %s — %d rows inserted (skipped %d unparseable)", ds, total, skipped)
    return total


async def backfill_stocks_day(s3, snap_date: date, bucket: str) -> int:
    """Load one day of stock flat file data into the database."""
    ds = snap_date.isoformat()
    year, month = ds[:4], ds[5:7]
    key = f"us_stocks_sip/day_aggs_v1/{year}/{month}/{ds}.csv.gz"

    buf = _stream_csv(s3, bucket, key)
    if buf is None:
        logger.info("  [stocks]  %s — no file", ds)
        return 0

    reader = csv.DictReader(buf)
    rows: list[dict] = []

    for raw in reader:
        ticker = raw.get("ticker", "")
        if not ticker or len(ticker) > 20:
            continue

        close_val = _safe_decimal(raw.get("close"))
        open_val = _safe_decimal(raw.get("open"))

        rows.append({
            "ticker": ticker,
            "snap_date": snap_date,
            "open": open_val,
            "high": _safe_decimal(raw.get("high")),
            "low": _safe_decimal(raw.get("low")),
            "close": close_val,
            "volume": _safe_int(raw.get("volume")),
            "vwap": None,
            "change_pct": None,
            "prev_close": None,
        })

    if not rows:
        logger.info("  [stocks]  %s — 0 rows", ds)
        return 0

    factory = get_session_factory()
    total = 0
    async with factory() as session:
        for i in range(0, len(rows), BATCH_SIZE):
            batch = rows[i : i + BATCH_SIZE]
            stmt = pg_insert(StockSnapshot).values(batch)
            update_cols = {
                c.name: c
                for c in stmt.excluded
                if c.name not in ("id", "ticker", "snap_date", "created_at")
            }
            stmt = stmt.on_conflict_do_update(
                index_elements=["ticker", "snap_date"],
                set_=update_cols,
            )
            await session.execute(stmt)
            total += len(batch)
        await session.commit()

    logger.info("  [stocks]  %s — %d rows inserted", ds, total)
    return total


async def run_backfill(date_from: date, date_to: date) -> None:
    """Backfill options + stock data for all trading days in range."""
    settings = get_settings()
    s3 = _get_s3()
    bucket = settings.polygon_flatfiles_bucket
    trading_days = _trading_days(date_from, date_to)

    logger.info("=== Backfill: %s to %s (%d trading days) ===", date_from, date_to, len(trading_days))
    t0 = time.monotonic()

    total_options = 0
    total_stocks = 0

    for day in trading_days:
        logger.info("Processing %s ...", day.isoformat())
        total_options += await backfill_options_day(s3, day, bucket)
        total_stocks += await backfill_stocks_day(s3, day, bucket)

    elapsed = time.monotonic() - t0
    logger.info(
        "\n=== Backfill complete in %.1fs ===\n"
        "  Trading days: %d\n"
        "  Option rows:  %d\n"
        "  Stock rows:   %d",
        elapsed,
        len(trading_days),
        total_options,
        total_stocks,
    )

    await dispose_engine()


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill historical data from Polygon flat files")
    parser.add_argument("--days", type=int, default=30, help="Calendar days to look back (default 30)")
    parser.add_argument("--from", dest="date_from", type=str, default=None, help="Start date YYYY-MM-DD")
    parser.add_argument("--to", dest="date_to", type=str, default=None, help="End date YYYY-MM-DD")
    args = parser.parse_args()

    if args.date_from and args.date_to:
        d_from = date.fromisoformat(args.date_from)
        d_to = date.fromisoformat(args.date_to)
    else:
        d_to = date.today() - timedelta(days=1)
        d_from = d_to - timedelta(days=args.days - 1)

    asyncio.run(run_backfill(d_from, d_to))


if __name__ == "__main__":
    main()
