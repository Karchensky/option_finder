"""Check whether the US stock market is currently open."""

import logging

from src.ingestion.client import polygon_get
from src.ingestion.schemas import MarketStatus

logger = logging.getLogger(__name__)


async def get_market_status() -> MarketStatus:
    """Query Polygon for the current market status."""
    data = await polygon_get("/v1/marketstatus/now")
    status = MarketStatus.model_validate(data)
    logger.info("market status: %s", status.market)
    return status


async def is_market_open() -> bool:
    """Return True if the regular session is currently open."""
    status = await get_market_status()
    return status.market == "open"
