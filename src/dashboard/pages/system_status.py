"""System Status — pipeline health, data freshness, and database stats."""

import streamlit as st
import pandas as pd
from datetime import date
from sqlalchemy import text

from src.dashboard.db import get_db


@st.cache_data(ttl=60)
def load_data_freshness() -> dict:
    with get_db() as db:
        result = db.execute(text("""
            SELECT
                (SELECT MAX(snap_date) FROM stock_snapshots) AS latest_stock_date,
                (SELECT MIN(snap_date) FROM stock_snapshots) AS earliest_stock_date,
                (SELECT COUNT(*) FROM stock_snapshots) AS stock_rows,
                (SELECT MAX(snap_date) FROM options_snapshots) AS latest_options_date,
                (SELECT MIN(snap_date) FROM options_snapshots) AS earliest_options_date,
                (SELECT COUNT(*) FROM options_snapshots) AS options_rows,
                (SELECT COUNT(*) FROM scoring_results) AS scoring_rows,
                (SELECT COUNT(*) FROM alerts_sent) AS alerts_rows,
                (SELECT COUNT(*) FROM scoring_results WHERE triggered) AS triggered_count,
                (SELECT COUNT(DISTINCT underlying_ticker) FROM options_snapshots) AS unique_underlyings,
                (SELECT COUNT(DISTINCT snap_date) FROM options_snapshots) AS trading_days
        """))
        row = result.fetchone()
        return dict(zip(result.keys(), row))


@st.cache_data(ttl=60)
def load_daily_data_counts() -> pd.DataFrame:
    with get_db() as db:
        query = text("""
            SELECT
                o.snap_date,
                COUNT(DISTINCT o.underlying_ticker) AS underlyings,
                COUNT(o.id) AS option_rows,
                COALESCE(s.scored, 0) AS scored,
                COALESCE(a.alerts, 0) AS alerts
            FROM options_snapshots o
            LEFT JOIN (
                SELECT snap_date, COUNT(*) AS scored FROM scoring_results GROUP BY snap_date
            ) s ON s.snap_date = o.snap_date
            LEFT JOIN (
                SELECT alert_date, COUNT(*) AS alerts FROM alerts_sent WHERE status = 'sent' GROUP BY alert_date
            ) a ON a.alert_date = o.snap_date
            GROUP BY o.snap_date, s.scored, a.alerts
            ORDER BY o.snap_date DESC
            LIMIT 30
        """)
        result = db.execute(query)
        rows = result.fetchall()
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows, columns=result.keys())


@st.cache_data(ttl=60)
def load_top_underlyings() -> pd.DataFrame:
    with get_db() as db:
        query = text("""
            SELECT
                underlying_ticker,
                COUNT(*) AS total_snapshots,
                SUM(volume) AS total_volume,
                MAX(snap_date) AS latest_date
            FROM options_snapshots
            WHERE volume IS NOT NULL AND volume > 0
            GROUP BY underlying_ticker
            ORDER BY total_volume DESC
            LIMIT 25
        """)
        result = db.execute(query)
        rows = result.fetchall()
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows, columns=result.keys())


@st.cache_data(ttl=60)
def load_table_sizes() -> pd.DataFrame:
    with get_db() as db:
        query = text("""
            SELECT
                c.relname AS table_name,
                pg_size_pretty(pg_total_relation_size(c.oid)) AS total_size,
                pg_size_pretty(pg_relation_size(c.oid)) AS data_size,
                pg_size_pretty(pg_indexes_size(c.oid)) AS index_size,
                s.n_live_tup AS live_rows
            FROM pg_class c
            JOIN pg_stat_user_tables s ON s.relname = c.relname
            WHERE c.relkind = 'r'
            ORDER BY pg_total_relation_size(c.oid) DESC
        """)
        result = db.execute(query)
        rows = result.fetchall()
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows, columns=result.keys())


# --- Main ---
st.title("System Status")

# Data freshness KPIs
freshness = load_data_freshness()

col1, col2, col3, col4 = st.columns(4)
col1.metric("Options Rows", f"{freshness['options_rows']:,}")
col2.metric("Stock Rows", f"{freshness['stock_rows']:,}")
col3.metric("Trading Days", freshness["trading_days"])
col4.metric("Unique Underlyings", freshness["unique_underlyings"])

col5, col6, col7, col8 = st.columns(4)
col5.metric("Latest Options Date", str(freshness["latest_options_date"] or "N/A"))
col6.metric("Earliest Options Date", str(freshness["earliest_options_date"] or "N/A"))
col7.metric("Scoring Results", f"{freshness['scoring_rows']:,}")
col8.metric("Alerts Sent", f"{freshness['alerts_rows']:,}")

# Pipeline status
latest = freshness.get("latest_options_date")
if latest:
    days_stale = (date.today() - latest).days
    if days_stale == 0:
        st.success("Pipeline data is current (today).")
    elif days_stale == 1:
        st.info("Pipeline data is 1 day old (may be normal if market was closed).")
    elif days_stale <= 3:
        st.warning(f"Pipeline data is {days_stale} days old. Check if scanner is running.")
    else:
        st.error(f"Pipeline data is {days_stale} days stale. Scanner may be stopped.")
else:
    st.error("No options data found in the database.")

# Daily breakdown
st.subheader("Daily Data Breakdown")
daily_df = load_daily_data_counts()
if not daily_df.empty:
    st.dataframe(
        daily_df,
        width="stretch",
        column_config={
            "snap_date": st.column_config.DateColumn("Date"),
            "option_rows": st.column_config.NumberColumn("Options", format="%d"),
        },
    )

# Table sizes
st.subheader("Database Table Sizes")
sizes_df = load_table_sizes()
if not sizes_df.empty:
    st.dataframe(sizes_df, width="stretch")

# Top underlyings by volume
st.subheader("Top Underlyings by Volume")
top_df = load_top_underlyings()
if not top_df.empty:
    st.dataframe(
        top_df,
        width="stretch",
        column_config={
            "total_volume": st.column_config.NumberColumn("Total Volume", format="%d"),
        },
    )
