"""Option Finder -- Streamlit Dashboard."""

from pathlib import Path

import streamlit as st

st.set_page_config(
    page_title="Option Finder",
    layout="wide",
    initial_sidebar_state="expanded",
)

_pages_dir = Path(__file__).parent / "pages"

alert_feed = st.Page(str(_pages_dir / "alert_feed.py"), title="Alert Feed", default=True)
ticker_lookup = st.Page(str(_pages_dir / "ticker_lookup.py"), title="Ticker Lookup")
system_status = st.Page(str(_pages_dir / "system_status.py"), title="System Status")

pg = st.navigation([alert_feed, ticker_lookup, system_status])
pg.run()
