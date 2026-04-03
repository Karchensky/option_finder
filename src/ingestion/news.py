"""Fetch recent news articles for a ticker via Polygon."""

import logging

from src.ingestion.client import polygon_get
from src.ingestion.schemas import NewsArticle

logger = logging.getLogger(__name__)


async def fetch_ticker_news(ticker: str, limit: int = 10) -> list[NewsArticle]:
    """Return recent news articles mentioning *ticker*."""
    data = await polygon_get("/v2/reference/news", params={"ticker": ticker, "limit": limit})
    articles = [NewsArticle.model_validate(a) for a in data.get("results") or []]
    logger.debug("fetched %d news articles for %s", len(articles), ticker)
    return articles
