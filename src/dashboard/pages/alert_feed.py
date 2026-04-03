"""Alert Feed — live and recent alerts with score breakdowns."""

import streamlit as st
import pandas as pd
import plotly.express as px
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
                o.implied_volatility
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
    today_stats = daily_stats[daily_stats["snap_date"] == date.today()]
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
    st.plotly_chart(fig, use_container_width=True)

# Alerts table
st.subheader("Sent Alerts")
if status_filter:
    alerts_df = load_alerts(date_from, date_to, min_score, status_filter)
    if alerts_df.empty:
        st.info("No alerts match these filters. Adjust the date range or score threshold.")
    else:
        st.dataframe(
            alerts_df,
            use_container_width=True,
            column_config={
                "composite_score": st.column_config.NumberColumn("Score", format="%.2f"),
                "alert_date": st.column_config.DateColumn("Date"),
            },
        )
else:
    st.warning("Select at least one alert status to view.")

# Top scoring contracts
st.subheader("Top Scoring Contracts")
scoring_df = load_scoring_results(date_from, date_to, min_score)
if scoring_df.empty:
    st.info("No scoring results in this range. The scanner may not have run yet, or no contracts exceeded the score threshold.")
else:
    display_cols = [
        "snap_date", "underlying_ticker", "option_ticker", "composite_score",
        "contract_type", "strike_price", "expiration_date", "volume",
        "open_interest", "implied_volatility", "triggered", "already_priced_in",
    ]
    existing_cols = [c for c in display_cols if c in scoring_df.columns]
    st.dataframe(
        scoring_df[existing_cols],
        use_container_width=True,
        column_config={
            "composite_score": st.column_config.NumberColumn("Score", format="%.2f"),
            "strike_price": st.column_config.NumberColumn("Strike", format="$%.2f"),
            "implied_volatility": st.column_config.NumberColumn("IV", format="%.4f"),
        },
    )
