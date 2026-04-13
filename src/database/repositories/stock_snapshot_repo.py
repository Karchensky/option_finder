"""Repository for stock snapshot CRUD operations."""

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import StockSnapshot


class StockSnapshotRepo:
    """Persistence layer for stock price snapshots."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_snapshot(self, data: dict) -> None:
        """Insert or update a stock snapshot (conflict on ticker + date)."""
        stmt = pg_insert(StockSnapshot).values(**data)
        stmt = stmt.on_conflict_do_update(
            index_elements=["ticker", "snap_date"],
            set_={k: v for k, v in data.items() if k not in ("ticker", "snap_date")},
        )
        await self._session.execute(stmt)

    _BATCH_SIZE = 2000

    async def upsert_many(self, rows: list[dict]) -> None:
        """Bulk upsert a list of stock snapshot dicts (batched to avoid exceeding asyncpg's 32k parameter limit)."""
        if not rows:
            return
        for i in range(0, len(rows), self._BATCH_SIZE):
            chunk = rows[i : i + self._BATCH_SIZE]
            stmt = pg_insert(StockSnapshot).values(chunk)
            update_cols = {c.name: c for c in stmt.excluded if c.name not in ("id", "ticker", "snap_date", "created_at")}
            stmt = stmt.on_conflict_do_update(
                index_elements=["ticker", "snap_date"],
                set_=update_cols,
            )
            await self._session.execute(stmt)
        await self._session.flush()

    async def get_by_ticker_date(self, ticker: str, snap_date: date) -> StockSnapshot | None:
        """Fetch a single snapshot by ticker and date."""
        stmt = select(StockSnapshot).where(
            StockSnapshot.ticker == ticker,
            StockSnapshot.snap_date == snap_date,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_change_pct_history(
        self,
        ticker: str,
        as_of_date: date,
        lookback_days: int = 20,
    ) -> list[float]:
        """Return daily change_pct values over the baseline window.

        Used to compute realized volatility for normalizing the underlying_z
        scoring factor.
        """
        start_date = as_of_date - timedelta(days=lookback_days * 2)
        stmt = (
            select(StockSnapshot.change_pct)
            .where(
                StockSnapshot.ticker == ticker,
                StockSnapshot.snap_date >= start_date,
                StockSnapshot.snap_date < as_of_date,
                StockSnapshot.change_pct.is_not(None),
            )
            .order_by(StockSnapshot.snap_date.desc())
            .limit(lookback_days)
        )
        result = await self._session.execute(stmt)
        return [float(row[0]) for row in result.fetchall()]

    async def get_movers(self, snap_date: date, min_change_pct: float | Decimal = 2.0) -> list[StockSnapshot]:
        """Return stocks that moved more than *min_change_pct* on *snap_date*."""
        stmt = (
            select(StockSnapshot)
            .where(
                StockSnapshot.snap_date == snap_date,
                (StockSnapshot.change_pct > min_change_pct) | (StockSnapshot.change_pct < -min_change_pct),
            )
            .order_by(StockSnapshot.change_pct.desc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
