"""Tests for alert email formatting."""

from datetime import datetime

from src.alerts.formatter import format_digest_email
from src.scoring.models import FactorScore, ScoreBreakdown


def _make_breakdown(
    ticker: str = "AAPL",
    score: float = 8.5,
    triggered: bool = True,
) -> ScoreBreakdown:
    return ScoreBreakdown(
        ticker=ticker,
        contract=f"O:{ticker}260417C00155000",
        composite_score=score,
        factors={
            "vol_z": FactorScore(raw=5000, z_score=3.5, weight=0.18, contribution=0.63),
            "prem_z": FactorScore(raw=2100000, z_score=2.8, weight=0.13, contribution=0.364),
            "iv_z": FactorScore(raw=0.45, z_score=2.1, weight=0.13, contribution=0.273),
            "vol_oi_z": FactorScore(raw=2.5, z_score=4.0, weight=0.12, contribution=0.48),
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


def test_digest_single_alert_subject():
    bd = _make_breakdown()
    msg = format_digest_email([bd])
    assert "1 alert" in msg["Subject"]
    assert "8.5" in msg["Subject"]


def test_digest_multiple_alerts_subject():
    bd1 = _make_breakdown(ticker="AAPL", score=9.2)
    bd2 = _make_breakdown(ticker="TSLA", score=8.0)
    msg = format_digest_email([bd1, bd2])
    assert "2 alerts" in msg["Subject"]
    assert "9.2" in msg["Subject"]


def test_digest_has_html_and_text():
    bd = _make_breakdown()
    msg = format_digest_email([bd])
    payloads = msg.get_payload()
    assert len(payloads) == 2
    content_types = [p.get_content_type() for p in payloads]
    assert "text/plain" in content_types
    assert "text/html" in content_types


def _get_decoded(msg, content_type: str) -> str:
    part = [p for p in msg.get_payload() if p.get_content_type() == content_type][0]
    raw = part.get_payload(decode=True)
    return raw.decode() if isinstance(raw, bytes) else raw


def test_digest_contains_factor_data():
    bd = _make_breakdown()
    msg = format_digest_email([bd])
    html_body = _get_decoded(msg, "text/html")
    assert "vol_z" in html_body
    assert "prem_z" in html_body


def test_digest_contains_all_tickers():
    bd1 = _make_breakdown(ticker="AAPL", score=9.0)
    bd2 = _make_breakdown(ticker="TSLA", score=8.0)
    msg = format_digest_email([bd1, bd2])
    html_body = _get_decoded(msg, "text/html")
    assert "AAPL" in html_body
    assert "TSLA" in html_body


def test_digest_sorted_by_score_descending():
    bd1 = _make_breakdown(ticker="LOW", score=7.5)
    bd2 = _make_breakdown(ticker="HIGH", score=9.5)
    msg = format_digest_email([bd1, bd2])
    text_body = _get_decoded(msg, "text/plain")
    high_pos = text_body.index("HIGH")
    low_pos = text_body.index("LOW")
    assert high_pos < low_pos


def test_digest_with_news():
    from src.ingestion.schemas import NewsArticle

    bd = _make_breakdown()
    news = [NewsArticle(title="AAPL beats earnings", published_utc=datetime(2026, 4, 2))]
    msg = format_digest_email([bd], news_by_ticker={"AAPL": news})
    html_body = _get_decoded(msg, "text/html")
    assert "AAPL beats earnings" in html_body
