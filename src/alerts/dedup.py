"""Alert deduplication — decide whether to send or suppress."""

import logging
from datetime import date, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from src.config.constants import ALERT_RETRY_MAX, DEDUP_SCORE_DELTA
from src.database.repositories.alert_repo import AlertRepo
from src.exceptions import AlertError
from src.scoring.models import ScoreBreakdown

logger = logging.getLogger(__name__)


async def should_send_alert(
    session: AsyncSession,
    breakdown: ScoreBreakdown,
    alert_date: date,
) -> tuple[bool, bool]:
    """Determine whether to send an alert.

    Returns (should_send, is_update):
      - should_send: True if the alert should be dispatched
      - is_update: True if this is a re-alert due to score increase
    """
    repo = AlertRepo(session)

    has_prior = await repo.has_prior_alert(breakdown.contract, alert_date)

    if has_prior:
        is_dup = await repo.check_dedup(
            option_ticker=breakdown.contract,
            alert_date=alert_date,
            new_score=breakdown.composite_score,
            score_delta=DEDUP_SCORE_DELTA,
        )
        if is_dup:
            logger.info(
                "dedup suppressed %s (score %.2f) — already alerted today, score increase < %.1f",
                breakdown.contract,
                breakdown.composite_score,
                DEDUP_SCORE_DELTA,
            )
            return False, False
        # Prior alert exists but score increased enough — send as update
        return True, True

    return True, False


async def log_alert_result(
    session: AsyncSession,
    breakdown: ScoreBreakdown,
    alert_date: date,
    status: str,
    subject: str = "",
) -> None:
    """Persist the alert outcome to the database."""
    repo = AlertRepo(session)
    await repo.log_alert({
        "option_ticker": breakdown.contract,
        "underlying_ticker": breakdown.ticker,
        "alert_date": alert_date,
        "composite_score": breakdown.composite_score,
        "sent_at": datetime.utcnow() if status == "sent" else None,
        "status": status,
        "retry_count": 0,
        "subject": subject,
    })
    await session.commit()


async def retry_failed_alerts(session: AsyncSession, alert_date: date) -> list:
    """Return failed alerts eligible for retry."""
    repo = AlertRepo(session)
    return await repo.get_pending_retries(alert_date, max_retries=ALERT_RETRY_MAX)
