"""SQLAlchemy 2.0 ORM models for all market-data and scoring tables."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.database.base import Base, TimestampMixin


class StockSnapshot(Base, TimestampMixin):
    """Daily/intra-day stock price snapshot from Polygon full-market endpoint."""

    __tablename__ = "stock_snapshots"
    __table_args__ = (
        Index("ix_stock_snapshots_ticker_date", "ticker", "snap_date", unique=True),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False)
    snap_date: Mapped[date] = mapped_column(Date, nullable=False)
    open: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    high: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    low: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    close: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    volume: Mapped[int | None] = mapped_column(BigInteger)
    vwap: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    change_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    prev_close: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    updated_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OptionsSnapshot(Base, TimestampMixin):
    """Per-contract option snapshot (greeks, IV, OI, volume, quote/trade)."""

    __tablename__ = "options_snapshots"
    __table_args__ = (
        Index("ix_options_snapshots_ticker_date", "option_ticker", "snap_date", unique=True),
        Index("ix_options_snapshots_underlying_exp", "underlying_ticker", "expiration_date"),
        Index("ix_options_snapshots_underlying_date", "underlying_ticker", "snap_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    option_ticker: Mapped[str] = mapped_column(String(30), nullable=False)
    underlying_ticker: Mapped[str] = mapped_column(String(20), nullable=False)
    snap_date: Mapped[date] = mapped_column(Date, nullable=False)

    # Contract details
    contract_type: Mapped[str] = mapped_column(String(4), nullable=False)  # call / put
    strike_price: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    expiration_date: Mapped[date] = mapped_column(Date, nullable=False)

    # Day OHLCV
    open: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    high: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    low: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    close: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    volume: Mapped[int | None] = mapped_column(BigInteger)
    vwap: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))

    # Options-specific
    open_interest: Mapped[int | None] = mapped_column(Integer)
    implied_volatility: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    delta: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    gamma: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    theta: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    vega: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))

    # Quote
    bid: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    ask: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    break_even_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))

    # Underlying context at snapshot time
    underlying_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))


class ScoringResult(Base, TimestampMixin):
    """Persisted score breakdown for a scored contract."""

    __tablename__ = "scoring_results"
    __table_args__ = (
        Index("ix_scoring_results_ticker_date", "option_ticker", "snap_date", unique=True),
        Index(
            "ix_scoring_results_triggered",
            "composite_score",
            postgresql_where="triggered = true",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    option_ticker: Mapped[str] = mapped_column(String(30), nullable=False)
    underlying_ticker: Mapped[str] = mapped_column(String(20), nullable=False)
    snap_date: Mapped[date] = mapped_column(Date, nullable=False)

    composite_score: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False)
    factors: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    underlying_move_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    already_priced_in: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    triggered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class AlertSent(Base, TimestampMixin):
    """Log of every alert sent, failed, or suppressed."""

    __tablename__ = "alerts_sent"
    __table_args__ = (
        Index("ix_alerts_sent_ticker_date", "option_ticker", "alert_date"),
        Index("ix_alerts_sent_status_date", "status", "alert_date", "option_ticker"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    option_ticker: Mapped[str] = mapped_column(String(30), nullable=False)
    underlying_ticker: Mapped[str] = mapped_column(String(20), nullable=False)
    alert_date: Mapped[date] = mapped_column(Date, nullable=False)
    composite_score: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # sent / failed / suppressed
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    subject: Mapped[str | None] = mapped_column(Text)


class TriggerCandidate(Base, TimestampMixin):
    """Intra-day trigger persistence tracker.

    Tracks contracts that have triggered across consecutive scan cycles
    within a single trading day.  A candidate is only promoted to a real
    alert once it has triggered in >= TRIGGER_CONFIRM_SCANS consecutive
    scans, filtering out ephemeral volume spikes that disappear between
    the 15-minute delayed snapshots.
    """

    __tablename__ = "trigger_candidates"
    __table_args__ = (
        Index("ix_trigger_candidates_ticker_date", "option_ticker", "alert_date", unique=True),
        Index("ix_trigger_candidates_underlying", "underlying_ticker", "alert_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    option_ticker: Mapped[str] = mapped_column(String(30), nullable=False)
    underlying_ticker: Mapped[str] = mapped_column(String(20), nullable=False)
    alert_date: Mapped[date] = mapped_column(Date, nullable=False)

    first_triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    trigger_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    missed_scans: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    peak_score: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False)
    peak_factors: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    expired: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class BacktestRun(Base, TimestampMixin):
    """Metadata and results for a single backtest run."""

    __tablename__ = "backtest_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_date: Mapped[date] = mapped_column(Date, nullable=False)
    date_from: Mapped[date] = mapped_column(Date, nullable=False)
    date_to: Mapped[date] = mapped_column(Date, nullable=False)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    results: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
