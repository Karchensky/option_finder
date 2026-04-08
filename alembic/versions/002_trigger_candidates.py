"""Add trigger_candidates table for scan persistence tracking.

Revision ID: 002
Revises: 001
Create Date: 2026-04-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "trigger_candidates",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("option_ticker", sa.String(30), nullable=False),
        sa.Column("underlying_ticker", sa.String(20), nullable=False),
        sa.Column("alert_date", sa.Date, nullable=False),
        sa.Column("first_triggered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_triggered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trigger_count", sa.Integer, nullable=False, server_default=sa.text("1")),
        sa.Column("peak_score", sa.Numeric(6, 3), nullable=False),
        sa.Column("peak_factors", postgresql.JSONB, nullable=False),
        sa.Column("confirmed", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("expired", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_trigger_candidates_ticker_date",
        "trigger_candidates",
        ["option_ticker", "alert_date"],
        unique=True,
    )
    op.create_index(
        "ix_trigger_candidates_underlying",
        "trigger_candidates",
        ["underlying_ticker", "alert_date"],
    )


def downgrade() -> None:
    op.drop_table("trigger_candidates")
