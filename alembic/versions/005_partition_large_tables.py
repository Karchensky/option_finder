"""Partition options_snapshots and scoring_results by snap_date (monthly).

This migration:
1. Renames the original tables to _old
2. Creates new partitioned tables with the same schema
3. Dynamically creates monthly partitions spanning existing data + 6 months ahead
4. Adds a DEFAULT partition for any data outside explicit ranges
5. Copies data from _old, verifies row counts, then drops _old
6. Recreates all indexes on the new partitioned tables

NOTE: Because PostgreSQL partitioned tables require the partition key in the
primary key, the PK changes from (id) to (id, snap_date).  SQLAlchemy's ORM
model already declares `id` as the primary key and `snap_date` as non-nullable;
the composite PK is transparent to the ORM since `id` is still autoincrement
and unique within each partition.

Revision ID: 005
Revises: 004
Create Date: 2026-04-13

"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _generate_monthly_partitions(table_parent: str, start_year: int, start_month: int,
                                  end_year: int, end_month: int) -> None:
    """Create monthly child partitions from (start_year, start_month) up to
    but not including (end_year, end_month)."""
    y, m = start_year, start_month
    while (y, m) < (end_year, end_month):
        nm = m + 1
        ny = y
        if nm > 12:
            nm = 1
            ny = y + 1
        name = f"{table_parent}_{y}_{m:02d}"
        start = f"{y}-{m:02d}-01"
        end = f"{ny}-{nm:02d}-01"
        op.execute(text(
            f"CREATE TABLE {name} PARTITION OF {table_parent} "
            f"FOR VALUES FROM ('{start}') TO ('{end}')"
        ))
        y, m = ny, nm if nm != 1 else 1
        if nm == 1:
            y = ny
            m = 1
        else:
            m = nm


def _get_row_count(table: str) -> int:
    """Return exact row count for a table."""
    conn = op.get_bind()
    result = conn.execute(text(f"SELECT count(*) FROM {table}"))
    return result.scalar()


def _create_partitioned_options_snapshots() -> None:
    """Create the partitioned version of options_snapshots."""
    op.execute(text("""
        CREATE TABLE options_snapshots_new (
            id BIGSERIAL,
            option_ticker VARCHAR(30) NOT NULL,
            underlying_ticker VARCHAR(20) NOT NULL,
            snap_date DATE NOT NULL,
            contract_type VARCHAR(4) NOT NULL,
            strike_price NUMERIC(12,4) NOT NULL,
            expiration_date DATE NOT NULL,
            "open" NUMERIC(12,4),
            high NUMERIC(12,4),
            low NUMERIC(12,4),
            "close" NUMERIC(12,4),
            volume BIGINT,
            vwap NUMERIC(12,4),
            open_interest INTEGER,
            implied_volatility NUMERIC(10,6),
            delta NUMERIC(10,6),
            gamma NUMERIC(10,6),
            theta NUMERIC(10,6),
            vega NUMERIC(10,6),
            bid NUMERIC(12,4),
            ask NUMERIC(12,4),
            break_even_price NUMERIC(12,4),
            underlying_price NUMERIC(12,4),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ,
            PRIMARY KEY (id, snap_date)
        ) PARTITION BY RANGE (snap_date)
    """))


def _create_partitioned_scoring_results() -> None:
    """Create the partitioned version of scoring_results."""
    op.execute(text("""
        CREATE TABLE scoring_results_new (
            id BIGSERIAL,
            option_ticker VARCHAR(30) NOT NULL,
            underlying_ticker VARCHAR(20) NOT NULL,
            snap_date DATE NOT NULL,
            composite_score NUMERIC(6,3) NOT NULL,
            factors JSONB NOT NULL,
            underlying_move_pct NUMERIC(8,4),
            already_priced_in BOOLEAN NOT NULL DEFAULT false,
            triggered BOOLEAN NOT NULL DEFAULT false,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ,
            PRIMARY KEY (id, snap_date)
        ) PARTITION BY RANGE (snap_date)
    """))


def _partition_table(old_name: str, new_name: str, create_fn: callable,
                     index_stmts: list[tuple]) -> None:
    """Generic: rename old -> create partitioned new -> copy -> verify -> drop old -> rename."""
    op.rename_table(old_name, f"{old_name}_old")

    # Create the partitioned parent
    create_fn()

    # Dynamically determine date range from existing data
    conn = op.get_bind()
    result = conn.execute(text(
        f"SELECT EXTRACT(YEAR FROM min(snap_date))::int, "
        f"       EXTRACT(MONTH FROM min(snap_date))::int, "
        f"       EXTRACT(YEAR FROM max(snap_date))::int, "
        f"       EXTRACT(MONTH FROM max(snap_date))::int "
        f"FROM {old_name}_old"
    ))
    row = result.fetchone()

    if row and row[0] is not None:
        min_y, min_m, max_y, max_m = int(row[0]), int(row[1]), int(row[2]), int(row[3])
        # Extend 6 months into the future for headroom
        end_m = max_m + 7
        end_y = max_y
        while end_m > 12:
            end_m -= 12
            end_y += 1
        _generate_monthly_partitions(new_name, min_y, min_m, end_y, end_m)
    else:
        # Empty table — just create a few months around now
        _generate_monthly_partitions(new_name, 2026, 1, 2027, 1)

    # Always add a DEFAULT partition for safety
    op.execute(text(f"CREATE TABLE {new_name}_default PARTITION OF {new_name} DEFAULT"))

    # Copy data
    old_count = _get_row_count(f"{old_name}_old")
    op.execute(text(f"INSERT INTO {new_name} SELECT * FROM {old_name}_old"))
    new_count = _get_row_count(new_name)

    if new_count != old_count:
        raise RuntimeError(
            f"Row count mismatch during {old_name} migration: "
            f"old={old_count} new={new_count}. Aborting — no data was dropped."
        )

    # Drop old table (and its indexes) BEFORE creating new indexes,
    # because PostgreSQL keeps index names when a table is renamed.
    op.drop_table(f"{old_name}_old")

    # Recreate indexes on the new partitioned table
    for idx_name, columns, kwargs in index_stmts:
        op.create_index(idx_name, new_name, columns, **kwargs)

    # Rename to the original table name
    op.rename_table(new_name, old_name)


def upgrade() -> None:
    _partition_table(
        old_name="options_snapshots",
        new_name="options_snapshots_new",
        create_fn=_create_partitioned_options_snapshots,
        index_stmts=[
            ("ix_options_snapshots_ticker_date", ["option_ticker", "snap_date"], {"unique": True}),
            ("ix_options_snapshots_underlying_exp", ["underlying_ticker", "expiration_date"], {}),
            ("ix_options_snapshots_underlying_date", ["underlying_ticker", "snap_date"], {}),
        ],
    )

    # scoring_results needs a partial index which op.create_index can't express,
    # so we handle it with raw SQL after the generic helper.
    _partition_table(
        old_name="scoring_results",
        new_name="scoring_results_new",
        create_fn=_create_partitioned_scoring_results,
        index_stmts=[
            ("ix_scoring_results_ticker_date", ["option_ticker", "snap_date"], {"unique": True}),
        ],
    )
    op.execute(text("""
        CREATE INDEX ix_scoring_results_triggered
        ON scoring_results (composite_score)
        WHERE triggered = true
    """))


def downgrade() -> None:
    # Reconstruct non-partitioned tables with full schema (not just SELECT *).
    # Back up your database before running this downgrade.

    # --- options_snapshots ---
    op.rename_table("options_snapshots", "options_snapshots_partitioned")
    op.execute(text("""
        CREATE TABLE options_snapshots (
            id BIGSERIAL PRIMARY KEY,
            option_ticker VARCHAR(30) NOT NULL,
            underlying_ticker VARCHAR(20) NOT NULL,
            snap_date DATE NOT NULL,
            contract_type VARCHAR(4) NOT NULL,
            strike_price NUMERIC(12,4) NOT NULL,
            expiration_date DATE NOT NULL,
            "open" NUMERIC(12,4),
            high NUMERIC(12,4),
            low NUMERIC(12,4),
            "close" NUMERIC(12,4),
            volume BIGINT,
            vwap NUMERIC(12,4),
            open_interest INTEGER,
            implied_volatility NUMERIC(10,6),
            delta NUMERIC(10,6),
            gamma NUMERIC(10,6),
            theta NUMERIC(10,6),
            vega NUMERIC(10,6),
            bid NUMERIC(12,4),
            ask NUMERIC(12,4),
            break_even_price NUMERIC(12,4),
            underlying_price NUMERIC(12,4),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ
        )
    """))
    op.execute(text(
        "INSERT INTO options_snapshots SELECT * FROM options_snapshots_partitioned"
    ))
    op.create_index(
        "ix_options_snapshots_ticker_date", "options_snapshots",
        ["option_ticker", "snap_date"], unique=True,
    )
    op.create_index(
        "ix_options_snapshots_underlying_exp", "options_snapshots",
        ["underlying_ticker", "expiration_date"],
    )
    op.create_index(
        "ix_options_snapshots_underlying_date", "options_snapshots",
        ["underlying_ticker", "snap_date"],
    )
    op.execute(text("DROP TABLE options_snapshots_partitioned CASCADE"))

    # --- scoring_results ---
    op.rename_table("scoring_results", "scoring_results_partitioned")
    op.execute(text("""
        CREATE TABLE scoring_results (
            id BIGSERIAL PRIMARY KEY,
            option_ticker VARCHAR(30) NOT NULL,
            underlying_ticker VARCHAR(20) NOT NULL,
            snap_date DATE NOT NULL,
            composite_score NUMERIC(6,3) NOT NULL,
            factors JSONB NOT NULL,
            underlying_move_pct NUMERIC(8,4),
            already_priced_in BOOLEAN NOT NULL DEFAULT false,
            triggered BOOLEAN NOT NULL DEFAULT false,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ
        )
    """))
    op.execute(text(
        "INSERT INTO scoring_results SELECT * FROM scoring_results_partitioned"
    ))
    op.create_index(
        "ix_scoring_results_ticker_date", "scoring_results",
        ["option_ticker", "snap_date"], unique=True,
    )
    op.execute(text("""
        CREATE INDEX ix_scoring_results_triggered
        ON scoring_results (composite_score)
        WHERE triggered = true
    """))
    op.execute(text("DROP TABLE scoring_results_partitioned CASCADE"))
