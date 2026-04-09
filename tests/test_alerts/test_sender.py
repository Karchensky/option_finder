"""Tests for email sender — verifies kill switch and SMTP interaction."""

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from unittest.mock import MagicMock, patch

import pytest

from src.alerts.sender import send_email


def _make_msg() -> MIMEMultipart:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Test Alert"
    msg.attach(MIMEText("test body", "plain"))
    return msg


def test_send_email_kill_switch_off(monkeypatch):
    """When ANOMALY_EMAIL_ENABLED is False, no SMTP call should be made."""
    monkeypatch.setenv("ANOMALY_EMAIL_ENABLED", "false")

    from src.config.settings import get_settings
    get_settings.cache_clear()

    msg = _make_msg()
    with patch("src.alerts.sender.smtplib") as mock_smtp:
        send_email(msg)
        mock_smtp.SMTP_SSL.assert_not_called()


def test_send_email_success(monkeypatch):
    monkeypatch.setenv("ANOMALY_EMAIL_ENABLED", "true")

    from src.config.settings import get_settings
    get_settings.cache_clear()

    msg = _make_msg()
    mock_server = MagicMock()

    with patch("src.alerts.sender.smtplib.SMTP_SSL") as mock_smtp_cls:
        mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)
        send_email(msg)
        mock_server.login.assert_called_once()
        mock_server.send_message.assert_called_once()
