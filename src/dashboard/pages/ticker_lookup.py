"""Ticker Lookup — deep-dive into a specific underlying's option chain and anomalies."""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import date, timedelta
from sqlalchemy import text

from src.dashboard.db import get_db


def search_tickers(query: str) -> list[str]:
    if not query or len(query) < 1:
        return []
    with get_db() as db:
        result = db.execute(
            text("""
                SELECT DISTINCT underlying_ticker
                FROM options_snapshots
                WHERE underlying_ticker ILIKE :q
                ORDER BY underlying_ticker
                LIMIT 20
            """),
            {"q": f"{query}%"},
        )
        return [row[0] for row in result.fetchall()]


def load_option_chain(ticker: str, snap_date: date) -> pd.DataFrame:
    with get_db() as db:
        query = text("""
            SELECT
                o.option_ticker,
                o.contract_type,
                o.strike_price,
                o.expiration_date,
                o.volume,
                o.open_interest,
                o.implied_volatility,
                o.delta,
                o.bid,
                o.ask,
                o.close,
                o.underlying_price,
                s.composite_score,
                s.triggered
            FROM options_snapshots o
            LEFT JOIN scoring_results s
                ON s.option_ticker = o.option_ticker AND s.snap_date = o.snap_date
            WHERE o.underlying_ticker = :ticker AND o.snap_date = :snap_date
            ORDER BY o.expiration_date, o.strike_price
        """)
        result = db.execute(query, {"ticker": ticker, "snap_date": snap_date})
        rows = result.fetchall()
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows, columns=result.keys())


def load_volume_history(ticker: str, days: int = 30) -> pd.DataFrame:
    with get_db() as db:
        query = text("""
            SELECT
                o.snap_date,
                SUM(o.volume) AS total_volume,
                SUM(o.open_interest) AS total_oi,
                COUNT(*) AS contracts,
                MAX(COALESCE(s.composite_score, 0)) AS max_score
            FROM options_snapshots o
            LEFT JOIN scoring_results s
                ON s.option_ticker = o.option_ticker AND s.snap_date = o.snap_date
            WHERE o.underlying_ticker = :ticker
              AND o.snap_date >= CURRENT_DATE - :days
            GROUP BY o.snap_date
            ORDER BY o.snap_date
        """)
        result = db.execute(query, {"ticker": ticker, "days": days})
        rows = result.fetchall()
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows, columns=result.keys())


def load_stock_history(ticker: str, days: int = 30) -> pd.DataFrame:
    with get_db() as db:
        query = text("""
            SELECT snap_date, open, high, low, close, volume, change_pct
            FROM stock_snapshots
            WHERE ticker = :ticker AND snap_date >= CURRENT_DATE - :days
            ORDER BY snap_date
        """)
        result = db.execute(query, {"ticker": ticker, "days": days})
        rows = result.fetchall()
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows, columns=result.keys())


# --- Sidebar ---
st.sidebar.header("Ticker Lookup")
ticker_input = st.sidebar.text_input("Search ticker", "").upper().strip()

matches = search_tickers(ticker_input) if ticker_input else []
if matches:
    selected_ticker = st.sidebar.selectbox("Select ticker", matches)
elif ticker_input:
    st.sidebar.warning(f"No options data found for '{ticker_input}'")
    selected_ticker = None
else:
    selected_ticker = None

lookup_date = st.sidebar.date_input("Snapshot date", value=date.today(), max_value=date.today())

# --- Main ---
st.title("Ticker Lookup")

if not selected_ticker:
    st.info("Enter a ticker symbol in the sidebar to look up its options chain and anomaly history.")
    st.stop()

st.header(f"{selected_ticker}")

# Stock price chart
stock_df = load_stock_history(selected_ticker, 30)
if not stock_df.empty:
    col1, col2, col3 = st.columns(3)
    latest = stock_df.iloc[-1]
    col1.metric("Close", f"${float(latest['close']):,.2f}" if latest["close"] else "N/A")
    col2.metric("Volume", f"{int(latest['volume']):,}" if latest["volume"] else "N/A")
    change = float(latest["change_pct"]) if latest["change_pct"] else 0
    col3.metric("Change %", f"{change:.2f}%", delta=f"{change:.2f}%")

    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=stock_df["snap_date"],
        open=stock_df["open"],
        high=stock_df["high"],
        low=stock_df["low"],
        close=stock_df["close"],
        name="Price",
    ))
    fig.update_layout(title=f"{selected_ticker} Price (30d)", height=350, margin=dict(t=40, b=20), xaxis_rangeslider_visible=False)
    st.plotly_chart(fig, use_container_width=True)

# Options volume/OI history
vol_df = load_volume_history(selected_ticker, 30)
if not vol_df.empty:
    fig2 = go.Figure()
    fig2.add_trace(go.Bar(x=vol_df["snap_date"], y=vol_df["total_volume"], name="Volume", marker_color="#636EFA"))
    fig2.add_trace(go.Scatter(x=vol_df["snap_date"], y=vol_df["total_oi"], name="Open Interest", yaxis="y2", line=dict(color="#EF553B")))
    fig2.update_layout(
        title="Options Volume & OI (30d)",
        yaxis=dict(title="Volume"),
        yaxis2=dict(title="Open Interest", overlaying="y", side="right"),
        height=300,
        margin=dict(t=40, b=20),
    )
    st.plotly_chart(fig2, use_container_width=True)

# Option chain for selected date
st.subheader(f"Option Chain — {lookup_date}")
chain_df = load_option_chain(selected_ticker, lookup_date)
if chain_df.empty:
    st.info(f"No option chain data for {selected_ticker} on {lookup_date}.")
else:
    tab_calls, tab_puts = st.tabs(["Calls", "Puts"])
    display_cols = [
        "option_ticker", "strike_price", "expiration_date", "volume", "open_interest",
        "implied_volatility", "delta", "bid", "ask", "close", "composite_score", "triggered",
    ]
    existing = [c for c in display_cols if c in chain_df.columns]
    col_config = {
        "strike_price": st.column_config.NumberColumn("Strike", format="$%.2f"),
        "composite_score": st.column_config.NumberColumn("Score", format="%.2f"),
        "implied_volatility": st.column_config.NumberColumn("IV", format="%.4f"),
        "bid": st.column_config.NumberColumn("Bid", format="$%.2f"),
        "ask": st.column_config.NumberColumn("Ask", format="$%.2f"),
        "close": st.column_config.NumberColumn("Last", format="$%.2f"),
    }

    with tab_calls:
        calls = chain_df[chain_df["contract_type"] == "call"][existing]
        if calls.empty:
            st.info("No call options for this date.")
        else:
            st.dataframe(calls, use_container_width=True, column_config=col_config)

    with tab_puts:
        puts = chain_df[chain_df["contract_type"] == "put"][existing]
        if puts.empty:
            st.info("No put options for this date.")
        else:
            st.dataframe(puts, use_container_width=True, column_config=col_config)
