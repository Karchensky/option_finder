"""Estimate upcoming earnings dates using Polygon financials endpoint.

Uses /vX/reference/financials to fetch historical quarterly filing dates,
then projects the next earnings date from the observed cadence.
"""

import logging
from datetime import date, timedelta

from src.ingestion.client import polygon_get

logger = logging.getLogger(__name__)

EARNINGS_LOOKAHEAD_DAYS = 14
EARNINGS_LOOKBACK_DAYS = 3


async def _fetch_filing_dates(ticker: str) -> list[date]:
    """Return recent quarterly filing dates for *ticker*, newest first."""
    try:
        data = await polygon_get(
            "/vX/reference/financials",
            params={
                "ticker": ticker,
                "limit": "8",
                "order": "desc",
                "sort": "filing_date",
                "timeframe": "quarterly",
            },
        )
    except Exception:
        logger.debug("financials lookup failed for %s", ticker)
        return []

    dates: list[date] = []
    for r in data.get("results") or []:
        fd = r.get("filing_date")
        if not fd:
            continue
        try:
            dates.append(date.fromisoformat(fd))
        except ValueError:
            continue
    return dates


def _estimate_next_filing(filing_dates: list[date]) -> date | None:
    """Project the next earnings date from observed quarterly intervals.

    Takes 2+ sorted-descending filing dates, computes the median interval,
    and adds it to the most recent filing date.
    """
    if len(filing_dates) < 2:
        return None

    intervals: list[int] = []
    for i in range(len(filing_dates) - 1):
        gap = (filing_dates[i] - filing_dates[i + 1]).days
        if 60 <= gap <= 120:
            intervals.append(gap)

    if not intervals:
        return None

    intervals.sort()
    median_interval = intervals[len(intervals) // 2]
    return filing_dates[0] + timedelta(days=median_interval)


async def fetch_next_earnings_date(
    ticker: str,
    as_of: date | None = None,
) -> date | None:
    """Return the nearest earnings date (past or upcoming) within the window.

    Checks both historical filings and a projected next filing.
    Returns None if no earnings fall within the relevant window
    (LOOKBACK..LOOKAHEAD days from *as_of*).
    """
    today = as_of or date.today()
    window_start = today - timedelta(days=EARNINGS_LOOKBACK_DAYS)
    window_end = today + timedelta(days=EARNINGS_LOOKAHEAD_DAYS)

    filing_dates = await _fetch_filing_dates(ticker)
    if not filing_dates:
        return None

    candidates: list[date] = list(filing_dates)

    projected = _estimate_next_filing(filing_dates)
    if projected is not None:
        candidates.append(projected)

    best: date | None = None
    best_distance = float("inf")

    for d in candidates:
        if d < window_start or d > window_end:
            continue
        distance = abs((d - today).days)
        if distance < best_distance:
            best_distance = distance
            best = d

    if best is not None:
        logger.debug(
            "earnings for %s: %s (%+d days from today)",
            ticker, best, (best - today).days,
        )
    return best


def days_until_earnings(
    earnings_date: date | None,
    as_of: date | None = None,
) -> int | None:
    """Signed days until earnings. Positive = upcoming, negative = past."""
    if earnings_date is None:
        return None
    today = as_of or date.today()
    return (earnings_date - today).days
