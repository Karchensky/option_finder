"""Alert Feed — live and recent alerts with score breakdowns and factor detail."""

import json

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from datetime import date, timedelta
from sqlalchemy import text

from src.dashboard.db import get_db


def load_alerts(date_from: date, date_to: date, min_score: float, status_filter: list[str]) -> pd.DataFrame:
    with get_db() as db:
        placeholders = ", ".join(f":s{i}" for i in range(len(status_filter)))
        params = {
            "date_from": date_from,
            "date_to": date_to,
            "min_score": min_score,
        }
        for i, s in enumerate(status_filter):
            params[f"s{i}"] = s

        query = text(f"""
            SELECT
                a.alert_date,
                a.underlying_ticker,
                a.option_ticker,
                a.composite_score,
                a.status,
                a.sent_at,
                a.subject,
                a.created_at
            FROM alerts_sent a
            WHERE a.alert_date BETWEEN :date_from AND :date_to
              AND a.composite_score >= :min_score
              AND a.status IN ({placeholders})
            ORDER BY a.composite_score DESC, a.created_at DESC
        """)
        result = db.execute(query, params)
        rows = result.fetchall()
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows, columns=result.keys())


def load_scoring_results(date_from: date, date_to: date, min_score: float) -> pd.DataFrame:
    with get_db() as db:
        query = text("""
            SELECT
                s.snap_date,
                s.underlying_ticker,
                s.option_ticker,
                s.composite_score,
                s.triggered,
                s.already_priced_in,
                s.factors,
                s.underlying_move_pct,
                o.contract_type,
                o.strike_price,
                o.expiration_date,
                o.volume,
                o.open_interest,
                o.implied_volatility,
                o.bid,
                o.ask,
                o.close AS option_price,
                o.underlying_price
            FROM scoring_results s
            LEFT JOIN options_snapshots o
                ON o.option_ticker = s.option_ticker AND o.snap_date = s.snap_date
            WHERE s.snap_date BETWEEN :date_from AND :date_to
              AND s.composite_score >= :min_score
            ORDER BY s.composite_score DESC
            LIMIT 500
        """)
        result = db.execute(query, {"date_from": date_from, "date_to": date_to, "min_score": min_score})
        rows = result.fetchall()
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows, columns=result.keys())


def load_daily_stats(days: int = 30) -> pd.DataFrame:
    with get_db() as db:
        query = text("""
            SELECT
                snap_date,
                COUNT(*) AS contracts_scored,
                COUNT(*) FILTER (WHERE triggered) AS triggered,
                AVG(composite_score) AS avg_score,
                MAX(composite_score) AS max_score
            FROM scoring_results
            WHERE snap_date >= CURRENT_DATE - :days
            GROUP BY snap_date
            ORDER BY snap_date
        """)
        result = db.execute(query, {"days": days})
        rows = result.fetchall()
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows, columns=result.keys())


def load_trigger_candidates(alert_date: date) -> pd.DataFrame:
    with get_db() as db:
        query = text("""
            SELECT
                tc.option_ticker,
                tc.underlying_ticker,
                tc.trigger_count,
                tc.peak_score,
                tc.confirmed,
                tc.expired,
                tc.first_triggered_at,
                tc.last_triggered_at,
                tc.peak_factors
            FROM trigger_candidates tc
            WHERE tc.alert_date = :alert_date
            ORDER BY tc.peak_score DESC
        """)
        result = db.execute(query, {"alert_date": alert_date})
        rows = result.fetchall()
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows, columns=result.keys())


def _safe_float(val: object, default: float = 0.0) -> float:
    """Convert a possibly-None value to float, returning *default* when None."""
    return float(val) if val is not None else default


def _safe_int(val: object, default: int = 0) -> int:
    """Convert a possibly-None value to int, returning *default* when None."""
    return int(val) if val is not None else default


def _parse_factors(factors_raw) -> dict:
    """Safely parse a factors column value (JSONB or string)."""
    if isinstance(factors_raw, dict):
        return factors_raw
    if isinstance(factors_raw, str):
        try:
            return json.loads(factors_raw)
        except (json.JSONDecodeError, TypeError):
            return {}
    return {}


def _render_factor_chart(factors: dict, title: str = "Factor Contributions") -> go.Figure | None:
    """Horizontal bar chart showing each factor's weighted contribution."""
    if not factors:
        return None

    names = []
    contributions = []
    z_scores = []

    for key in sorted(factors.keys(), key=lambda k: abs(factors[k].get("contribution", 0)), reverse=True):
        f = factors[key]
        names.append(key.replace("_z", "").replace("_", " ").title())
        contributions.append(f.get("contribution", 0))
        z_scores.append(f.get("z_score", 0))

    colors = ["#2ecc71" if c > 0 else "#e74c3c" for c in contributions]

    fig = go.Figure(go.Bar(
        x=contributions,
        y=names,
        orientation="h",
        marker_color=colors,
        text=[f"z={z:+.1f}" for z in z_scores],
        textposition="outside",
    ))
    fig.update_layout(
        title=title,
        xaxis_title="Weighted Contribution",
        yaxis=dict(autorange="reversed"),
        height=max(200, len(names) * 32),
        margin=dict(l=120, r=40, t=40, b=30),
    )
    return fig


# --- Sidebar ---
st.sidebar.header("Filters")

date_range = st.sidebar.date_input(
    "Date range",
    value=(date.today() - timedelta(days=7), date.today()),
    max_value=date.today(),
)
if isinstance(date_range, tuple) and len(date_range) == 2:
    date_from, date_to = date_range
else:
    date_from = date_to = date.today()

min_score = st.sidebar.slider("Min composite score", 0.0, 10.0, 5.0, 0.5)

status_options = ["sent", "failed", "suppressed"]
status_filter = st.sidebar.multiselect("Alert status", status_options, default=["sent"])

# --- Main Area ---
st.title("Alert Feed")

# KPI row
daily_stats = load_daily_stats(30)
if not daily_stats.empty:
    col1, col2, col3, col4 = st.columns(4)
    total_triggered = int(daily_stats["triggered"].sum())
    col1.metric("Alerts Triggered (30d)", total_triggered)
    col2.metric("Contracts Scored (30d)", f"{int(daily_stats['contracts_scored'].sum()):,}")
    col3.metric("Avg Score (30d)", f"{daily_stats['avg_score'].mean():.2f}")
    col4.metric("Peak Score (30d)", f"{daily_stats['max_score'].max():.2f}")

    fig = px.bar(
        daily_stats,
        x="snap_date",
        y="contracts_scored",
        color="triggered",
        title="Daily Scoring Volume",
        labels={"snap_date": "Date", "contracts_scored": "Contracts Scored"},
    )
    fig.update_layout(height=300, margin=dict(t=40, b=20))
    st.plotly_chart(fig, width="stretch")

# --- Trigger Candidates (persistence view) ---
st.subheader("Trigger Candidates (Today)")
st.caption("Contracts must trigger across multiple consecutive scans before an alert fires.")
candidates_df = load_trigger_candidates(date.today())
if candidates_df.empty:
    st.info("No trigger candidates today — the scanner may not have run yet.")
else:
    confirmed = candidates_df[candidates_df["confirmed"] == True]  # noqa: E712
    pending = candidates_df[(candidates_df["confirmed"] == False) & (candidates_df["expired"] == False)]  # noqa: E712
    expired = candidates_df[candidates_df["expired"] == True]  # noqa: E712

    c1, c2, c3 = st.columns(3)
    c1.metric("Confirmed", len(confirmed))
    c2.metric("Pending", len(pending))
    c3.metric("Expired", len(expired))

    if not confirmed.empty:
        st.markdown("**Confirmed triggers:**")
        st.dataframe(
            confirmed[["underlying_ticker", "option_ticker", "peak_score", "trigger_count",
                        "first_triggered_at", "last_triggered_at"]],
            width="stretch",
            column_config={
                "peak_score": st.column_config.NumberColumn("Peak Score", format="%.2f"),
            },
        )

    if not pending.empty:
        st.markdown("**Pending confirmation:**")
        st.dataframe(
            pending[["underlying_ticker", "option_ticker", "peak_score", "trigger_count",
                      "first_triggered_at"]],
            width="stretch",
            column_config={
                "peak_score": st.column_config.NumberColumn("Peak Score", format="%.2f"),
            },
        )

# --- Sent Alerts table ---
st.subheader("Sent Alerts")
if status_filter:
    alerts_df = load_alerts(date_from, date_to, min_score, status_filter)
    if alerts_df.empty:
        st.info("No alerts match these filters. Adjust the date range or score threshold.")
    else:
        st.dataframe(
            alerts_df,
            width="stretch",
            column_config={
                "composite_score": st.column_config.NumberColumn("Score", format="%.2f"),
                "alert_date": st.column_config.DateColumn("Date"),
            },
        )
else:
    st.warning("Select at least one alert status to view.")

# --- Top Scoring Contracts with Factor Breakdown ---
st.subheader("Top Scoring Contracts")
scoring_df = load_scoring_results(date_from, date_to, min_score)
if scoring_df.empty:
    st.info("No scoring results in this range. The scanner may not have run yet, or no contracts exceeded the score threshold.")
else:
    display_cols = [
        "snap_date", "underlying_ticker", "option_ticker", "composite_score",
        "contract_type", "strike_price", "expiration_date", "volume",
        "open_interest", "implied_volatility", "option_price", "underlying_price",
        "triggered", "already_priced_in",
    ]
    existing_cols = [c for c in display_cols if c in scoring_df.columns]
    st.dataframe(
        scoring_df[existing_cols],
        width="stretch",
        column_config={
            "composite_score": st.column_config.NumberColumn("Score", format="%.2f"),
            "strike_price": st.column_config.NumberColumn("Strike", format="$%.2f"),
            "implied_volatility": st.column_config.NumberColumn("IV", format="%.4f"),
            "option_price": st.column_config.NumberColumn("Opt Price", format="$%.2f"),
            "underlying_price": st.column_config.NumberColumn("Undl Price", format="$%.2f"),
        },
    )

    # Factor drill-down for each triggered contract
    triggered_rows = scoring_df[scoring_df["triggered"] == True]  # noqa: E712
    if not triggered_rows.empty:
        st.subheader("Factor Breakdown — Triggered Contracts")
        for idx, row in triggered_rows.head(20).iterrows():
            factors = _parse_factors(row.get("factors"))
            if not factors:
                continue

            label = f"{row['underlying_ticker']}  |  {row['option_ticker']}  |  Score: {row['composite_score']:.2f}"
            with st.expander(label, expanded=False):
                col_left, col_right = st.columns([3, 2])

                with col_left:
                    fig = _render_factor_chart(factors, title=f"Factor Contributions — {row['option_ticker']}")
                    if fig:
                        st.plotly_chart(fig, width="stretch")

                with col_right:
                    st.markdown("**Contract Details**")
                    details = {
                        "Type": (row.get("contract_type") or "").upper(),
                        "Strike": f"${_safe_float(row.get('strike_price')):,.2f}",
                        "Expiration": str(row.get("expiration_date") or ""),
                        "Volume": f"{_safe_int(row.get('volume')):,}",
                        "Open Interest": f"{_safe_int(row.get('open_interest')):,}",
                        "IV": f"{_safe_float(row.get('implied_volatility')):.4f}",
                        "Option Price": f"${_safe_float(row.get('option_price')):,.2f}",
                        "Underlying": f"${_safe_float(row.get('underlying_price')):,.2f}",
                        "Undl Move": f"{_safe_float(row.get('underlying_move_pct')):+.2f}%",
                        "Priced In": "Yes" if row.get("already_priced_in") else "No",
                    }
                    for k, v in details.items():
                        st.text(f"{k:>16s}: {v}")

                    st.markdown("**Factor Scores**")
                    factor_table = []
                    for key in sorted(factors.keys(), key=lambda k: abs(factors[k].get("contribution", 0)), reverse=True):
                        f = factors[key]
                        factor_table.append({
                            "Factor": key,
                            "Raw": f"{f.get('raw', 0):,.2f}",
                            "Z-Score": f"{f.get('z_score', 0):+.2f}",
                            "Weight": f"{f.get('weight', 0):.2f}",
                            "Contribution": f"{f.get('contribution', 0):+.4f}",
                        })
                    st.dataframe(pd.DataFrame(factor_table), width="stretch", hide_index=True)
