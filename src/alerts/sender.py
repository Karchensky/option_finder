"""SMTP email delivery with retry logic."""

import logging
import smtplib

from src.config.settings import get_settings
from src.exceptions import AlertError

logger = logging.getLogger(__name__)


def send_email(msg) -> bool:
    """Send a MIMEMultipart email via Gmail SMTP/SSL.

    Returns True if the email was actually delivered, False if skipped
    (kill-switch off, missing creds). Raises AlertError on SMTP failure.
    """
    settings = get_settings()

    if not settings.anomaly_email_enabled:
        logger.info("email kill-switch is OFF — alert not sent")
        return False

    if not settings.sender_email or not settings.email_password:
        logger.warning("email credentials not configured — alert not sent")
        return False

    msg["From"] = settings.sender_email
    msg["To"] = settings.recipient_email

    try:
        with smtplib.SMTP_SSL(settings.smtp_server, settings.smtp_port) as server:
            server.login(settings.sender_email, settings.email_password)
            server.send_message(msg)
        logger.info(
            "alert email sent to %s — subject: %s",
            settings.recipient_email,
            msg["Subject"],
        )
        return True
    except smtplib.SMTPException as exc:
        logger.error("SMTP error sending alert: %s", exc)
        raise AlertError(f"SMTP delivery failed: {exc}") from exc
    except OSError as exc:
        logger.error("network error sending alert: %s", exc)
        raise AlertError(f"Network error sending alert: {exc}") from exc
