"""Synchronous database access for Streamlit dashboard."""

import streamlit as st
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.config.settings import get_settings


@st.cache_resource
def get_sync_engine():
    """Return a cached synchronous SQLAlchemy engine."""
    settings = get_settings()
    url = settings.database_url
    return create_engine(url, pool_size=5, max_overflow=10, pool_pre_ping=True)


def get_db() -> Session:
    """Return a new synchronous session."""
    return Session(get_sync_engine())
