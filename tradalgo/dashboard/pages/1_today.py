from datetime import datetime

import streamlit as st

from tradalgo.clock import IST
from tradalgo.dashboard import queries
from tradalgo.dashboard.app import get_engine, get_settings

st.title("Today")

settings = get_settings()
engine = get_engine(settings)

trade_date = st.date_input("Date", value=datetime.now(IST).date())


@st.cache_data(ttl=15)
def _shortlist(_engine, d):
    return queries.shortlist_for_date(_engine, d)


@st.cache_data(ttl=15)
def _signals(_engine, d):
    return queries.signals_with_decisions(_engine, d)


@st.fragment(run_every=15)
def render() -> None:
    st.subheader("Shortlist")
    shortlist = _shortlist(engine, trade_date.isoformat())
    st.dataframe(shortlist, use_container_width=True)

    st.subheader("Signals & decisions")
    signals = _signals(engine, trade_date.isoformat())
    if not signals.empty:
        for col in ("regime", "market_regime"):
            if col in signals.columns:
                st.caption(f"{col}: {sorted(signals[col].dropna().unique().tolist())}")
    st.dataframe(signals, use_container_width=True)


render()
