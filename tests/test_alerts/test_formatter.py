"""Tests for alert email formatting."""

from datetime import datetime

from src.alerts.formatter import format_alert_email
from src.scoring.models import FactorScore, ScoreBreakdown


def _make_breakdown(score: float = 8.5, triggered: bool = True) -> ScoreBreakdown:
    return ScoreBreakdown(
        ticker="AAPL",
        contract="O:AAPL260417C00155000",
        composite_score=score,
        factors={
            "vol_z": FactorScore(raw=5000, z_score=3.5, weight=0.25, contribution=0.875),
            "prem_z": FactorScore(raw=2100000, z_score=2.8, weight=0.20, contribution=0.56),
        },
        underlying_move_pct=0.5,
        already_priced_in=False,
        timestamp=datetime(2026, 4, 3, 14, 30, 0),
        triggered=triggered,
        underlying_price=154.0,
        option_price=4.20,
        option_volume=5000,
        open_interest=12000,
        contract_type="call",
        expiration_date="2026-04-17",
        strike_price=155.0,
    )


def test_format_alert_email_subject():
    bd = _make_breakdown()
    msg = format_alert_email(bd)
    assert "AAPL" in msg["Subject"]
    assert "8.5" in msg["Subject"]


def test_format_alert_email_update_prefix():
    bd = _make_breakdown()
    msg = format_alert_email(bd, is_update=True)
    assert msg["Subject"].startswith("UPDATE:")


def test_format_alert_email_has_html_and_text():
    bd = _make_breakdown()
    msg = format_alert_email(bd)
    payloads = msg.get_payload()
    assert len(payloads) == 2
    content_types = [p.get_content_type() for p in payloads]
    assert "text/plain" in content_types
    assert "text/html" in content_types


def test_format_alert_email_contains_factor_data():
    bd = _make_breakdown()
    msg = format_alert_email(bd)
    html_part = [p for p in msg.get_payload() if p.get_content_type() == "text/html"][0]
    html_body = html_part.get_payload()
    assert "vol_z" in html_body
    assert "prem_z" in html_body


def test_format_alert_email_with_news():
    from src.ingestion.schemas import NewsArticle

    bd = _make_breakdown()
    news = [NewsArticle(title="AAPL beats earnings", published_utc=datetime(2026, 4, 2))]
    msg = format_alert_email(bd, news=news)
    html_part = [p for p in msg.get_payload() if p.get_content_type() == "text/html"][0]
    html_body = html_part.get_payload()
    assert "AAPL beats earnings" in html_body
