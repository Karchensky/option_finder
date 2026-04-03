"""Repository for scoring result persistence and queries."""

import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import ScoringResult

logger = logging.getLogger(__name__)


class ScoringRepo:
    """Persistence layer for scoring results."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save_result(self, data: dict) -> None:
        """Insert or update a scoring result."""
        stmt = pg_insert(ScoringResult).values(**data)
        stmt = stmt.on_conflict_do_update(
            index_elements=["option_ticker", "snap_date"],
            set_={k: v for k, v in data.items() if k not in ("option_ticker", "snap_date")},
        )
        await self._session.execute(stmt)

    async def save_many(self, rows: list[dict]) -> None:
        """Bulk upsert scoring results."""
        if not rows:
            return
        stmt = pg_insert(ScoringResult).values(rows)
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

    async def get_triggered(self, snap_date: date) -> list[ScoringResult]:
        """Return all triggered scoring results for a given date."""
        stmt = (
            select(ScoringResult)
            .where(
                ScoringResult.snap_date == snap_date,
                ScoringResult.triggered.is_(True),
            )
            .order_by(ScoringResult.composite_score.desc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
