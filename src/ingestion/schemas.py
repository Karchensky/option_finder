"""Pydantic models that validate Polygon API response payloads."""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Stock market snapshot
# ---------------------------------------------------------------------------

class StockDayBar(BaseModel):
    """Intra-day OHLCV bar embedded in the stock snapshot."""
    o: Decimal | None = Field(None, alias="o")
    h: Decimal | None = Field(None, alias="h")
    l: Decimal | None = Field(None, alias="l")  # noqa: E741
    c: Decimal | None = Field(None, alias="c")
    v: int | None = Field(None, alias="v")
    vw: Decimal | None = Field(None, alias="vw")


class StockTickerSnapshot(BaseModel):
    """Single entry from the full-market stock snapshot endpoint."""
    ticker: str
    day: StockDayBar | None = None
    prev_day: StockDayBar | None = None
    todaysChange: Decimal | None = None
    todaysChangePerc: Decimal | None = None
    updated: int | None = None  # nanosecond unix timestamp


# ---------------------------------------------------------------------------
# Option chain snapshot
# ---------------------------------------------------------------------------

class OptionDayBar(BaseModel):
    open: Decimal | None = None
    high: Decimal | None = None
    low: Decimal | None = None
    close: Decimal | None = None
    volume: int | None = None
    vwap: Decimal | None = None


class OptionDetails(BaseModel):
    contract_type: str
    exercise_style: str | None = None
    expiration_date: date
    shares_per_contract: int | None = 100
    strike_price: Decimal
    ticker: str


class OptionGreeks(BaseModel):
    delta: Decimal | None = None
    gamma: Decimal | None = None
    theta: Decimal | None = None
    vega: Decimal | None = None


class OptionLastQuote(BaseModel):
    bid: Decimal | None = None
    ask: Decimal | None = None
    bid_size: int | None = None
    ask_size: int | None = None
    midpoint: Decimal | None = None


class OptionUnderlyingAsset(BaseModel):
    ticker: str | None = None
    price: Decimal | None = None
    change_to_break_even: Decimal | None = None


class OptionSnapshotResult(BaseModel):
    """Single contract from /v3/snapshot/options/{underlying}."""
    break_even_price: Decimal | None = None
    day: OptionDayBar | None = None
    details: OptionDetails
    greeks: OptionGreeks | None = None
    implied_volatility: Decimal | None = None
    open_interest: int | None = None
    underlying_asset: OptionUnderlyingAsset | None = None
    last_quote: OptionLastQuote | None = None


# ---------------------------------------------------------------------------
# Aggregates
# ---------------------------------------------------------------------------

class AggBar(BaseModel):
    """Single OHLCV bar from /v2/aggs/ticker/... endpoint."""
    o: Decimal | None = None
    h: Decimal | None = None
    l: Decimal | None = None  # noqa: E741
    c: Decimal | None = None
    v: int | None = None
    vw: Decimal | None = None
    t: int | None = None  # Unix ms timestamp
    n: int | None = None  # number of trades


# ---------------------------------------------------------------------------
# News
# ---------------------------------------------------------------------------

class NewsArticle(BaseModel):
    """Single article from /v2/reference/news."""
    id: str | None = None
    title: str
    description: str | None = None
    published_utc: datetime | None = None
    article_url: str | None = None
    tickers: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Market status
# ---------------------------------------------------------------------------

class MarketStatus(BaseModel):
    """Response from /v1/marketstatus/now."""
    market: str  # "open", "closed", "extended-hours"
    earlyHours: bool | None = None
    afterHours: bool | None = None
    serverTime: str | None = None
