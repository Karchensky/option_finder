"""Repository for alert deduplication and logging."""

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import AlertSent


class AlertRepo:
    """Persistence layer for sent / suppressed / failed alerts."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def log_alert(self, data: dict) -> AlertSent:
        """Insert a new alert log row and return the ORM instance."""
        alert = AlertSent(**data)
        self._session.add(alert)
        await self._session.flush()
        return alert

    async def check_dedup(
        self,
        option_ticker: str,
        alert_date: date,
        new_score: float,
        score_delta: float = 1.0,
    ) -> bool:
        """Return True if the alert should be suppressed (duplicate).

        An alert is a duplicate when a prior alert for the same contract
        on the same trading day exists and the new score has NOT increased
        by at least *score_delta*.
        """
        stmt = (
            select(AlertSent)
            .where(
                AlertSent.option_ticker == option_ticker,
                AlertSent.alert_date == alert_date,
                AlertSent.status == "sent",
            )
            .order_by(AlertSent.composite_score.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        previous = result.scalar_one_or_none()

        if previous is None:
            return False

        return float(new_score - float(previous.composite_score)) < score_delta

    async def has_prior_alert(self, option_ticker: str, alert_date: date) -> bool:
        """Return True if any sent alert exists for this contract today."""
        stmt = (
            select(AlertSent)
            .where(
                AlertSent.option_ticker == option_ticker,
                AlertSent.alert_date == alert_date,
                AlertSent.status == "sent",
            )
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def get_pending_retries(self, alert_date: date, max_retries: int = 3) -> list[AlertSent]:
        """Return failed alerts eligible for retry."""
        stmt = (
            select(AlertSent)
            .where(
                AlertSent.alert_date == alert_date,
                AlertSent.status == "failed",
                AlertSent.retry_count < max_retries,
            )
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def mark_sent(self, alert_id: int) -> None:
        """Update an alert's status to sent."""
        stmt = select(AlertSent).where(AlertSent.id == alert_id)
        result = await self._session.execute(stmt)
        alert = result.scalar_one()
        alert.status = "sent"
        await self._session.flush()
