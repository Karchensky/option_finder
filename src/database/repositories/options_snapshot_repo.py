"""Repository for options snapshot CRUD and baseline queries."""

import logging
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import OptionsSnapshot

logger = logging.getLogger(__name__)


class OptionsSnapshotRepo:
    """Persistence layer for per-contract option snapshots."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_snapshot(self, data: dict) -> None:
        """Insert or update a single options snapshot."""
        stmt = pg_insert(OptionsSnapshot).values(**data)
        stmt = stmt.on_conflict_do_update(
            index_elements=["option_ticker", "snap_date"],
            set_={k: v for k, v in data.items() if k not in ("option_ticker", "snap_date")},
        )
        await self._session.execute(stmt)

    _BATCH_SIZE = 1000

    async def upsert_many(self, rows: list[dict]) -> None:
        """Bulk upsert a list of options snapshot dicts (batched to avoid exceeding asyncpg's 32k parameter limit)."""
        if not rows:
            return
        for i in range(0, len(rows), self._BATCH_SIZE):
            chunk = rows[i : i + self._BATCH_SIZE]
            stmt = pg_insert(OptionsSnapshot).values(chunk)
            update_cols = {
                c.name: c
                for c in stmt.excluded
                if c.name not in ("id", "option_ticker", "snap_date", "created_at")
            }
            stmt = stmt.on_conflict_do_update(
                index_elements=["option_ticker", "snap_date"],
                set_=update_cols,
            )
            await self._session.execute(stmt)
        await self._session.flush()

    async def get_baseline(
        self,
        option_ticker: str,
        as_of_date: date,
        lookback_days: int = 20,
    ) -> list[OptionsSnapshot]:
        """Fetch the rolling baseline window for a contract, excluding *as_of_date*."""
        start_date = as_of_date - timedelta(days=lookback_days * 2)
        stmt = (
            select(OptionsSnapshot)
            .where(
                OptionsSnapshot.option_ticker == option_ticker,
                OptionsSnapshot.snap_date >= start_date,
                OptionsSnapshot.snap_date < as_of_date,
            )
            .order_by(OptionsSnapshot.snap_date.desc())
            .limit(lookback_days)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_underlying_date(
        self,
        underlying_ticker: str,
        snap_date: date,
    ) -> list[OptionsSnapshot]:
        """Fetch all option snapshots for an underlying on a given date."""
        stmt = (
            select(OptionsSnapshot)
            .where(
                OptionsSnapshot.underlying_ticker == underlying_ticker,
                OptionsSnapshot.snap_date == snap_date,
            )
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_chain_volume_by_underlying(
        self,
        underlying_ticker: str,
        snap_date: date,
    ) -> list[OptionsSnapshot]:
        """Return all contracts with volume > 0 for an underlying on a date."""
        stmt = (
            select(OptionsSnapshot)
            .where(
                OptionsSnapshot.underlying_ticker == underlying_ticker,
                OptionsSnapshot.snap_date == snap_date,
                OptionsSnapshot.volume > 0,
            )
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_chain_volume_history(
        self,
        underlying_ticker: str,
        as_of_date: date,
        lookback_days: int = 20,
    ) -> list[float]:
        """Return daily total chain volumes for an underlying over the baseline window.

        Used by the chain_vol_z factor to compare today's aggregate chain
        activity against its 20-day baseline.
        """
        start_date = as_of_date - timedelta(days=lookback_days * 2)
        stmt = (
            select(func.sum(OptionsSnapshot.volume))
            .where(
                OptionsSnapshot.underlying_ticker == underlying_ticker,
                OptionsSnapshot.snap_date >= start_date,
                OptionsSnapshot.snap_date < as_of_date,
                OptionsSnapshot.volume > 0,
            )
            .group_by(OptionsSnapshot.snap_date)
            .order_by(OptionsSnapshot.snap_date.desc())
            .limit(lookback_days)
        )
        result = await self._session.execute(stmt)
        return [float(row[0]) for row in result.fetchall() if row[0] is not None]
