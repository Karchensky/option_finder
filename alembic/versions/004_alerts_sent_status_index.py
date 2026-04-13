"""Add composite index on alerts_sent(status, alert_date, option_ticker).

Speeds up dedup queries that filter by status='sent' and retry queries
that filter by status='failed'.

Revision ID: 004
Revises: 003
Create Date: 2026-04-13

"""
from typing import Sequence, Union

from alembic import op

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_alerts_sent_status_date",
        "alerts_sent",
        ["status", "alert_date", "option_ticker"],
    )


def downgrade() -> None:
    op.drop_index("ix_alerts_sent_status_date", table_name="alerts_sent")
