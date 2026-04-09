"""Format scoring breakdowns into HTML + plain-text alert emails."""

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from src.ingestion.schemas import NewsArticle
from src.scoring.models import ScoreBreakdown


def _factor_rows_html(breakdown: ScoreBreakdown) -> str:
    rows = ""
    for key, fs in sorted(breakdown.factors.items(), key=lambda kv: -abs(kv[1].contribution)):
        rows += (
            f"<tr>"
            f"<td style='padding:4px 8px;'>{key}</td>"
            f"<td style='padding:4px 8px;text-align:right;'>{fs.raw:,.2f}</td>"
            f"<td style='padding:4px 8px;text-align:right;'>{fs.z_score:+.2f}</td>"
            f"<td style='padding:4px 8px;text-align:right;'>{fs.weight:.2f}</td>"
            f"<td style='padding:4px 8px;text-align:right;'>{fs.contribution:+.4f}</td>"
            f"</tr>"
        )
    return rows


def _factor_rows_text(breakdown: ScoreBreakdown) -> str:
    lines = []
    for key, fs in sorted(breakdown.factors.items(), key=lambda kv: -abs(kv[1].contribution)):
        lines.append(f"  {key:<16s}  raw={fs.raw:>12,.2f}  z={fs.z_score:+.2f}  w={fs.weight:.2f}  c={fs.contribution:+.4f}")
    return "\n".join(lines)


def _fmt_price(val: float | None) -> str:
    return f"${val:,.2f}" if val is not None else "N/A"


def _fmt_int(val: int | None) -> str:
    return f"{val:,}" if val is not None else "N/A"


def _single_alert_html(breakdown: ScoreBreakdown) -> str:
    """Build HTML block for one triggered contract inside the digest."""
    direction = "CALL" if breakdown.contract_type.lower() == "call" else "PUT"
    return f"""
    <div style="border:1px solid #ddd;border-radius:6px;padding:12px;margin-bottom:16px;">
      <h3 style="color:#d32f2f;margin-top:0;">{breakdown.ticker} — {direction} — Score {breakdown.composite_score:.2f}/10</h3>
      <table style="border-collapse:collapse;margin-bottom:8px;">
        <tr><td><b>Contract</b></td><td>{breakdown.contract}</td></tr>
        <tr><td><b>Strike</b></td><td>{_fmt_price(breakdown.strike_price)} {direction} exp {breakdown.expiration_date}</td></tr>
        <tr><td><b>Option Price</b></td><td>{_fmt_price(breakdown.option_price)}</td></tr>
        <tr><td><b>Volume</b></td><td>{_fmt_int(breakdown.option_volume)}</td></tr>
        <tr><td><b>Open Interest</b></td><td>{_fmt_int(breakdown.open_interest)}</td></tr>
        <tr><td><b>Underlying Price</b></td><td>{_fmt_price(breakdown.underlying_price)}</td></tr>
        <tr><td><b>Underlying Move</b></td><td>{breakdown.underlying_move_pct:+.2f}%</td></tr>
      </table>
      <details>
        <summary>Factor Breakdown</summary>
        <table style="border-collapse:collapse;border:1px solid #ccc;margin-top:4px;">
          <tr style="background:#f0f0f0;">
            <th style="padding:4px 8px;">Factor</th>
            <th style="padding:4px 8px;">Raw</th>
            <th style="padding:4px 8px;">Z-Score</th>
            <th style="padding:4px 8px;">Weight</th>
            <th style="padding:4px 8px;">Contribution</th>
          </tr>
          {_factor_rows_html(breakdown)}
        </table>
      </details>
    </div>"""


def _single_alert_text(breakdown: ScoreBreakdown) -> str:
    """Build plain-text block for one triggered contract."""
    direction = "CALL" if breakdown.contract_type.lower() == "call" else "PUT"
    return f"""--- {breakdown.ticker} | {direction} | Score {breakdown.composite_score:.2f}/10 ---
Contract:         {breakdown.contract}
Strike:           {_fmt_price(breakdown.strike_price)} {direction} exp {breakdown.expiration_date}
Option Price:     {_fmt_price(breakdown.option_price)}
Volume:           {_fmt_int(breakdown.option_volume)}
Open Interest:    {_fmt_int(breakdown.open_interest)}
Underlying Price: {_fmt_price(breakdown.underlying_price)}
Underlying Move:  {breakdown.underlying_move_pct:+.2f}%

Factor Breakdown:
{_factor_rows_text(breakdown)}
"""


def format_digest_email(
    breakdowns: list[ScoreBreakdown],
    news_by_ticker: dict[str, list[NewsArticle]] | None = None,
) -> MIMEMultipart:
    """Build ONE digest email containing all triggered alerts for a scan cycle.

    Breakdowns are sorted by composite score descending.
    """
    news_by_ticker = news_by_ticker or {}
    sorted_bds = sorted(breakdowns, key=lambda b: -b.composite_score)

    tickers_involved = sorted({b.ticker for b in sorted_bds})
    count = len(sorted_bds)
    top_score = sorted_bds[0].composite_score if sorted_bds else 0.0
    subject = f"Option Finder Digest: {count} alert{'s' if count != 1 else ''} — top score {top_score:.1f}"

    ts = sorted_bds[0].timestamp.strftime("%Y-%m-%d %H:%M:%S") if sorted_bds else "N/A"

    # --- HTML body ---
    alerts_html = "\n".join(_single_alert_html(b) for b in sorted_bds)

    news_html = ""
    for ticker in tickers_involved:
        articles = news_by_ticker.get(ticker, [])
        if articles:
            items = "".join(
                f"<li>{a.title} <small>({a.published_utc.strftime('%Y-%m-%d %H:%M') if a.published_utc else 'N/A'})</small></li>"
                for a in articles[:3]
            )
            news_html += f"<h3>{ticker} — Recent News</h3><ul>{items}</ul>"

    html = f"""
    <html><body style="font-family:Arial,sans-serif;max-width:800px;">
    <h2 style="color:#d32f2f;">Option Finder Alert Digest</h2>
    <p><b>{count}</b> anomalous contract{'s' if count != 1 else ''} detected across
       <b>{len(tickers_involved)}</b> underlying{'s' if len(tickers_involved) != 1 else ''}:
       {', '.join(tickers_involved)}</p>
    <p>Scan timestamp: {ts} UTC</p>
    <hr>
    {alerts_html}
    {news_html}
    <p style="color:#888;font-size:12px;">
      Generated by Option Finder. This is not financial advice.
    </p>
    </body></html>
    """

    # --- Plain text body ---
    alerts_text = "\n".join(_single_alert_text(b) for b in sorted_bds)

    news_text = ""
    for ticker in tickers_involved:
        articles = news_by_ticker.get(ticker, [])
        if articles:
            lines = "\n".join(f"  - {a.title}" for a in articles[:3])
            news_text += f"\n{ticker} — Recent News:\n{lines}\n"

    text = f"""Option Finder Alert Digest
{'=' * 40}
{count} anomalous contract{'s' if count != 1 else ''} detected across {len(tickers_involved)} underlying{'s' if len(tickers_involved) != 1 else ''}: {', '.join(tickers_involved)}
Scan timestamp: {ts} UTC

{alerts_text}
{news_text}
---
Generated by Option Finder. This is not financial advice.
"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg.attach(MIMEText(text, "plain"))
    msg.attach(MIMEText(html, "html"))
    return msg


def format_alert_email(
    breakdown: ScoreBreakdown,
    news: list[NewsArticle] | None = None,
    is_update: bool = False,
) -> MIMEMultipart:
    """Build an HTML+text MIME message for a single triggered alert.

    When *is_update* is True the subject line is prefixed with "UPDATE: "
    to distinguish re-alerts from initial triggers.
    """
    msg = format_digest_email(
        [breakdown],
        news_by_ticker={breakdown.ticker: news} if news else None,
    )
    if is_update:
        msg.replace_header("Subject", f"UPDATE: {msg['Subject']}")
    return msg
