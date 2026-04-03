"""Initial schema — stock snapshots, options snapshots, scoring results, alerts, backtests.

Revision ID: 001
Revises: None
Create Date: 2026-04-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "stock_snapshots",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("ticker", sa.String(20), nullable=False),
        sa.Column("snap_date", sa.Date, nullable=False),
        sa.Column("open", sa.Numeric(12, 4)),
        sa.Column("high", sa.Numeric(12, 4)),
        sa.Column("low", sa.Numeric(12, 4)),
        sa.Column("close", sa.Numeric(12, 4)),
        sa.Column("volume", sa.BigInteger),
        sa.Column("vwap", sa.Numeric(12, 4)),
        sa.Column("change_pct", sa.Numeric(8, 4)),
        sa.Column("prev_close", sa.Numeric(12, 4)),
        sa.Column("updated_ts", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_stock_snapshots_ticker_date", "stock_snapshots", ["ticker", "snap_date"], unique=True)

    op.create_table(
        "options_snapshots",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("option_ticker", sa.String(30), nullable=False),
        sa.Column("underlying_ticker", sa.String(20), nullable=False),
        sa.Column("snap_date", sa.Date, nullable=False),
        sa.Column("contract_type", sa.String(4), nullable=False),
        sa.Column("strike_price", sa.Numeric(12, 4), nullable=False),
        sa.Column("expiration_date", sa.Date, nullable=False),
        sa.Column("open", sa.Numeric(12, 4)),
        sa.Column("high", sa.Numeric(12, 4)),
        sa.Column("low", sa.Numeric(12, 4)),
        sa.Column("close", sa.Numeric(12, 4)),
        sa.Column("volume", sa.BigInteger),
        sa.Column("vwap", sa.Numeric(12, 4)),
        sa.Column("open_interest", sa.Integer),
        sa.Column("implied_volatility", sa.Numeric(10, 6)),
        sa.Column("delta", sa.Numeric(10, 6)),
        sa.Column("gamma", sa.Numeric(10, 6)),
        sa.Column("theta", sa.Numeric(10, 6)),
        sa.Column("vega", sa.Numeric(10, 6)),
        sa.Column("bid", sa.Numeric(12, 4)),
        sa.Column("ask", sa.Numeric(12, 4)),
        sa.Column("break_even_price", sa.Numeric(12, 4)),
        sa.Column("underlying_price", sa.Numeric(12, 4)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_options_snapshots_ticker_date", "options_snapshots", ["option_ticker", "snap_date"], unique=True)
    op.create_index("ix_options_snapshots_underlying_exp", "options_snapshots", ["underlying_ticker", "expiration_date"])
    op.create_index("ix_options_snapshots_underlying_date", "options_snapshots", ["underlying_ticker", "snap_date"])

    op.create_table(
        "scoring_results",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("option_ticker", sa.String(30), nullable=False),
        sa.Column("underlying_ticker", sa.String(20), nullable=False),
        sa.Column("snap_date", sa.Date, nullable=False),
        sa.Column("composite_score", sa.Numeric(6, 3), nullable=False),
        sa.Column("factors", postgresql.JSONB, nullable=False),
        sa.Column("underlying_move_pct", sa.Numeric(8, 4)),
        sa.Column("already_priced_in", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("triggered", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_scoring_results_ticker_date", "scoring_results", ["option_ticker", "snap_date"], unique=True)
    op.create_index(
        "ix_scoring_results_triggered",
        "scoring_results",
        ["composite_score"],
        postgresql_where=sa.text("triggered = true"),
    )

    op.create_table(
        "alerts_sent",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("option_ticker", sa.String(30), nullable=False),
        sa.Column("underlying_ticker", sa.String(20), nullable=False),
        sa.Column("alert_date", sa.Date, nullable=False),
        sa.Column("composite_score", sa.Numeric(6, 3), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("retry_count", sa.Integer, server_default=sa.text("0")),
        sa.Column("subject", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_alerts_sent_ticker_date", "alerts_sent", ["option_ticker", "alert_date"])

    op.create_table(
        "backtest_runs",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("run_date", sa.Date, nullable=False),
        sa.Column("date_from", sa.Date, nullable=False),
        sa.Column("date_to", sa.Date, nullable=False),
        sa.Column("parameters", postgresql.JSONB, nullable=False),
        sa.Column("results", postgresql.JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    op.drop_table("backtest_runs")
    op.drop_table("alerts_sent")
    op.drop_table("scoring_results")
    op.drop_table("options_snapshots")
    op.drop_table("stock_snapshots")
