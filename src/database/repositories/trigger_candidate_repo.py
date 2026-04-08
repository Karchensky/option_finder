"""Repository for trigger persistence tracking across scan cycles."""

import logging
from datetime import date, datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import TriggerCandidate

logger = logging.getLogger(__name__)


class TriggerCandidateRepo:
    """Persistence layer for intra-day trigger candidate tracking."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_candidate(self, data: dict) -> TriggerCandidate:
        """Insert a new candidate or increment its trigger count."""
        stmt = pg_insert(TriggerCandidate).values(**data)
        stmt = stmt.on_conflict_do_update(
            index_elements=["option_ticker", "alert_date"],
            set_={
                "last_triggered_at": data["last_triggered_at"],
                "trigger_count": TriggerCandidate.trigger_count + 1,
                "peak_score": stmt.excluded.peak_score,
                "peak_factors": stmt.excluded.peak_factors,
                "expired": False,
            },
        )
        await self._session.execute(stmt)
        await self._session.flush()

        result = await self._session.execute(
            select(TriggerCandidate).where(
                TriggerCandidate.option_ticker == data["option_ticker"],
                TriggerCandidate.alert_date == data["alert_date"],
            )
        )
        return result.scalar_one()

    async def expire_stale_candidates(
        self,
        alert_date: date,
        active_tickers: set[str],
    ) -> int:
        """Mark candidates that did NOT trigger in this scan as expired.

        Resetting them prevents non-consecutive triggers from accumulating.
        Returns the number of rows expired.
        """
        stmt = (
            update(TriggerCandidate)
            .where(
                TriggerCandidate.alert_date == alert_date,
                TriggerCandidate.expired.is_(False),
                TriggerCandidate.confirmed.is_(False),
                TriggerCandidate.option_ticker.not_in(active_tickers) if active_tickers else True,
            )
            .values(expired=True, trigger_count=0)
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        return result.rowcount

    async def mark_confirmed(self, option_ticker: str, alert_date: date) -> None:
        """Mark a candidate as confirmed (alert will be sent)."""
        stmt = (
            update(TriggerCandidate)
            .where(
                TriggerCandidate.option_ticker == option_ticker,
                TriggerCandidate.alert_date == alert_date,
            )
            .values(confirmed=True)
        )
        await self._session.execute(stmt)
        await self._session.flush()

    async def get_active_candidates(self, alert_date: date) -> list[TriggerCandidate]:
        """Return all non-expired, non-confirmed candidates for today."""
        stmt = (
            select(TriggerCandidate)
            .where(
                TriggerCandidate.alert_date == alert_date,
                TriggerCandidate.expired.is_(False),
                TriggerCandidate.confirmed.is_(False),
            )
            .order_by(TriggerCandidate.peak_score.desc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_confirmed_count(self, alert_date: date) -> int:
        """Return how many candidates have been confirmed today."""
        stmt = (
            select(TriggerCandidate)
            .where(
                TriggerCandidate.alert_date == alert_date,
                TriggerCandidate.confirmed.is_(True),
            )
        )
        result = await self._session.execute(stmt)
        return len(result.scalars().all())
