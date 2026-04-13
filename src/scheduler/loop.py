"""Continuous scan loop with resilience."""

import asyncio
import logging
import signal
import sys
import types
from datetime import datetime, time, timedelta

from src.config.constants import (
    CYCLE_RETRY_DELAY_S,
    EASTERN,
    MAX_CONSECUTIVE_FAILURES,
    SCAN_CYCLE_INTERVAL_S,
)
from src.database.engine import dispose_engine, get_engine
from src.ingestion.client import close_client, get_client
from src.scheduler.pipeline import run_scan_cycle

logger = logging.getLogger(__name__)

_shutdown_requested = False

MARKET_CLOSED_SLEEP_S = 300  # 5 min between checks when market is closed

# Business-hour window (ET) — scanner sleeps outside this range.
# Padded 30 min before open and 60 min after close for data settling.
_BIZ_OPEN = time(9, 0)
_BIZ_CLOSE = time(17, 0)
_BIZ_WEEKDAYS = range(0, 5)  # Mon=0 … Fri=4


def _seconds_until_next_window() -> float | None:
    """Return seconds until the next business window, or None if inside it now."""
    now = datetime.now(EASTERN)
    if now.weekday() in _BIZ_WEEKDAYS and _BIZ_OPEN <= now.time() <= _BIZ_CLOSE:
        return None  # inside window

    # Find the next weekday at _BIZ_OPEN
    target = now.replace(hour=_BIZ_OPEN.hour, minute=_BIZ_OPEN.minute, second=0, microsecond=0)
    if now.time() > _BIZ_CLOSE or now.weekday() not in _BIZ_WEEKDAYS:
        target += timedelta(days=1)
    while target.weekday() not in _BIZ_WEEKDAYS:
        target += timedelta(days=1)

    return (target - now).total_seconds()


def _request_shutdown(signum: int, frame: types.FrameType | None) -> None:
    global _shutdown_requested  # noqa: PLW0603
    logger.info("shutdown requested (signal %s) — finishing current cycle", signum)
    _shutdown_requested = True


async def startup_checks() -> None:
    """Verify critical dependencies before entering the scan loop."""
    from sqlalchemy import text

    engine = get_engine()
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    logger.info("database connection OK")

    client = get_client()
    resp = await client.get("/v1/marketstatus/now")
    resp.raise_for_status()
    logger.info("Polygon API connection OK (market status: %s)", resp.json().get("market"))


async def run_loop() -> None:
    """Main loop: run scan cycles, let the pipeline decide if market is open."""
    signal.signal(signal.SIGINT, _request_shutdown)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _request_shutdown)

    logger.info("Option Finder scan loop starting")
    await startup_checks()

    consecutive_failures = 0

    try:
        while not _shutdown_requested:
            # Sleep outside business hours instead of polling every 5 min
            sleep_for = _seconds_until_next_window()
            if sleep_for is not None:
                hours = sleep_for / 3600
                logger.info(
                    "outside business hours (Mon-Fri %s-%s ET) — sleeping %.1f hours",
                    _BIZ_OPEN.strftime("%H:%M"), _BIZ_CLOSE.strftime("%H:%M"), hours,
                )
                await asyncio.sleep(sleep_for)
                continue

            try:
                stats = await run_scan_cycle()
                consecutive_failures = 0
                logger.info("cycle stats: %s", stats)

                # If market was closed, the cycle returns almost instantly
                # with stocks_fetched=0. Sleep longer before checking again.
                if stats.get("stocks_fetched", 0) == 0:
                    logger.info("market closed — checking again in %ds", MARKET_CLOSED_SLEEP_S)
                    await asyncio.sleep(MARKET_CLOSED_SLEEP_S)
                else:
                    duration = stats.get("duration_s", 0)
                    sleep_s = max(0, SCAN_CYCLE_INTERVAL_S - duration)
                    if sleep_s > 0:
                        logger.info("next scan in %.0fs", sleep_s)
                        await asyncio.sleep(sleep_s)

            except Exception:
                consecutive_failures += 1
                logger.exception(
                    "scan cycle failed (%d consecutive)",
                    consecutive_failures,
                )
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    logger.critical(
                        "reached %d consecutive failures — alerting operator",
                        consecutive_failures,
                    )
                await asyncio.sleep(CYCLE_RETRY_DELAY_S)

    finally:
        logger.info("shutting down — disposing resources")
        await close_client()
        await dispose_engine()
        logger.info("Option Finder scan loop stopped")
