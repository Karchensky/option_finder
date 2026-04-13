"""Ticker Lookup — deep-dive into a specific underlying's option chain, anomalies, and chain context."""

import json

import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import streamlit as st
from datetime import date, timedelta
from sqlalchemy import text

from src.dashboard.db import get_db


def _safe_float(val: object, default: float = 0.0) -> float:
    """Convert a possibly-None value to float, returning *default* when None."""
    return float(val) if val is not None else default


def _safe_int(val: object, default: int = 0) -> int:
    """Convert a possibly-None value to int, returning *default* when None."""
    return int(val) if val is not None else default


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
                s.triggered,
                s.factors
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
                SUM(CASE WHEN o.contract_type = 'call' THEN o.volume ELSE 0 END) AS call_volume,
                SUM(CASE WHEN o.contract_type = 'put' THEN o.volume ELSE 0 END) AS put_volume,
                MAX(COALESCE(s.composite_score, 0)) AS max_score,
                COUNT(*) FILTER (WHERE COALESCE(s.triggered, false)) AS triggered_count
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


def load_trigger_history(ticker: str, days: int = 30) -> pd.DataFrame:
    """Load trigger candidates for this underlying over recent days."""
    with get_db() as db:
        query = text("""
            SELECT
                tc.alert_date,
                tc.option_ticker,
                tc.trigger_count,
                tc.peak_score,
                tc.confirmed,
                tc.expired,
                tc.first_triggered_at,
                tc.last_triggered_at
            FROM trigger_candidates tc
            WHERE tc.underlying_ticker = :ticker
              AND tc.alert_date >= CURRENT_DATE - :days
            ORDER BY tc.alert_date DESC, tc.peak_score DESC
        """)
        result = db.execute(query, {"ticker": ticker, "days": days})
        rows = result.fetchall()
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows, columns=result.keys())


def _parse_factors(factors_raw) -> dict:
    if isinstance(factors_raw, dict):
        return factors_raw
    if isinstance(factors_raw, str):
        try:
            return json.loads(factors_raw)
        except (json.JSONDecodeError, TypeError):
            return {}
    return {}


def _render_factor_chart(factors: dict, title: str = "") -> go.Figure | None:
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
    st.plotly_chart(fig, width="stretch")

# --- Chain-Level Context ---
st.subheader("Chain Volume Context (30d)")
vol_df = load_volume_history(selected_ticker, 30)
if not vol_df.empty:
    avg_vol = vol_df["total_volume"].mean()
    today_vol = vol_df[vol_df["snap_date"] == lookup_date]
    today_total = int(today_vol["total_volume"].iloc[0]) if not today_vol.empty else 0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Chain Volume (today)", f"{today_total:,}")
    c2.metric("Avg Chain Volume (30d)", f"{int(avg_vol):,}")
    ratio = today_total / avg_vol if avg_vol > 0 else 0
    c3.metric("Volume Ratio", f"{ratio:.1f}x", delta=f"{ratio - 1:.1f}x" if ratio != 0 else None)

    today_triggered = int(today_vol["triggered_count"].iloc[0]) if not today_vol.empty else 0
    c4.metric("Triggered Contracts", today_triggered)

    # Stacked call/put volume chart
    fig2 = go.Figure()
    fig2.add_trace(go.Bar(
        x=vol_df["snap_date"], y=vol_df["call_volume"], name="Call Volume",
        marker_color="#2ecc71",
    ))
    fig2.add_trace(go.Bar(
        x=vol_df["snap_date"], y=vol_df["put_volume"], name="Put Volume",
        marker_color="#e74c3c",
    ))
    fig2.add_trace(go.Scatter(
        x=vol_df["snap_date"], y=vol_df["total_oi"], name="Open Interest",
        yaxis="y2", line=dict(color="#3498db", width=2),
    ))

    # Mark days with triggers
    trigger_days = vol_df[vol_df["triggered_count"] > 0]
    if not trigger_days.empty:
        fig2.add_trace(go.Scatter(
            x=trigger_days["snap_date"],
            y=trigger_days["total_volume"],
            mode="markers",
            marker=dict(size=12, color="#f39c12", symbol="star", line=dict(width=1, color="black")),
            name="Trigger Day",
        ))

    fig2.update_layout(
        title="Options Volume: Calls vs Puts (30d)",
        barmode="stack",
        yaxis=dict(title="Volume"),
        yaxis2=dict(title="Open Interest", overlaying="y", side="right"),
        height=350,
        margin=dict(t=40, b=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    st.plotly_chart(fig2, width="stretch")

# --- Trigger History ---
trigger_df = load_trigger_history(selected_ticker, 30)
if not trigger_df.empty:
    st.subheader("Trigger History (30d)")
    confirmed = trigger_df[trigger_df["confirmed"] == True]  # noqa: E712
    if not confirmed.empty:
        st.markdown(f"**{len(confirmed)} confirmed triggers** in the last 30 days")
    st.dataframe(
        trigger_df,
        width="stretch",
        column_config={
            "peak_score": st.column_config.NumberColumn("Peak Score", format="%.2f"),
            "alert_date": st.column_config.DateColumn("Date"),
        },
        hide_index=True,
    )

# --- Option Chain for selected date ---
st.subheader(f"Option Chain — {lookup_date}")
chain_df = load_option_chain(selected_ticker, lookup_date)
if chain_df.empty:
    st.info(f"No option chain data for {selected_ticker} on {lookup_date}.")
else:
    # Volume by strike heatmap
    active_contracts = chain_df[chain_df["volume"].fillna(0) > 0].copy()
    if not active_contracts.empty:
        active_contracts["strike_price"] = active_contracts["strike_price"].astype(float)
        active_contracts["volume"] = active_contracts["volume"].astype(int)

        fig_strike = px.bar(
            active_contracts,
            x="strike_price",
            y="volume",
            color="contract_type",
            color_discrete_map={"call": "#2ecc71", "put": "#e74c3c"},
            title="Volume by Strike",
            labels={"strike_price": "Strike Price", "volume": "Volume"},
        )
        if not stock_df.empty:
            current_price = float(stock_df.iloc[-1]["close"]) if stock_df.iloc[-1]["close"] else None
            if current_price:
                fig_strike.add_vline(x=current_price, line_dash="dash", line_color="blue",
                                     annotation_text=f"${current_price:.0f}")
        fig_strike.update_layout(height=300, margin=dict(t=40, b=20))
        st.plotly_chart(fig_strike, width="stretch")

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
            st.dataframe(calls, width="stretch", column_config=col_config, hide_index=True)

    with tab_puts:
        puts = chain_df[chain_df["contract_type"] == "put"][existing]
        if puts.empty:
            st.info("No put options for this date.")
        else:
            st.dataframe(puts, width="stretch", column_config=col_config, hide_index=True)

    # Factor breakdown for triggered contracts on this chain
    triggered_in_chain = chain_df[chain_df["triggered"] == True]  # noqa: E712
    if not triggered_in_chain.empty:
        st.subheader("Triggered Contract Details")
        for _, row in triggered_in_chain.iterrows():
            factors = _parse_factors(row.get("factors"))
            if not factors:
                continue

            score = float(row["composite_score"]) if row["composite_score"] is not None else 0
            label = f"{row['option_ticker']}  |  Score: {score:.2f}  |  Vol: {int(row.get('volume', 0)):,}"
            with st.expander(label, expanded=True):
                col_chart, col_detail = st.columns([3, 2])

                with col_chart:
                    fig = _render_factor_chart(factors, title=row["option_ticker"])
                    if fig:
                        st.plotly_chart(fig, width="stretch")

                with col_detail:
                    st.markdown("**Snapshot at Trigger Time**")
                    detail = {
                        "Type": str(row.get("contract_type") or "").upper(),
                        "Strike": f"${_safe_float(row.get('strike_price')):,.2f}",
                        "Expiration": str(row.get("expiration_date") or ""),
                        "Volume": f"{_safe_int(row.get('volume')):,}",
                        "Open Interest": f"{_safe_int(row.get('open_interest')):,}",
                        "IV": f"{_safe_float(row.get('implied_volatility')):.4f}",
                        "Bid": f"${_safe_float(row.get('bid')):,.2f}",
                        "Ask": f"${_safe_float(row.get('ask')):,.2f}",
                        "Last": f"${_safe_float(row.get('close')):,.2f}",
                        "Underlying": f"${_safe_float(row.get('underlying_price')):,.2f}",
                        "Delta": f"{_safe_float(row.get('delta')):.4f}" if row.get("delta") is not None else "N/A",
                    }
                    for k, v in detail.items():
                        st.text(f"{k:>16s}: {v}")
