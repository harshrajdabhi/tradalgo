from datetime import date, timedelta

import streamlit as st

from tradalgo.dashboard import queries
from tradalgo.dashboard.app import get_engine, get_settings

st.title("Journal")

settings = get_settings()
engine = get_engine(settings)

c1, c2, c3, c4 = st.columns(4)
date_from = c1.date_input("From", value=date.today() - timedelta(days=30))
date_to = c2.date_input("To", value=date.today())
strategy = c3.selectbox("Strategy", options=[None, "orb", "gap", "vwap", "pdhl", "pullback", "range_breakout"],
                        format_func=lambda s: s or "all")
symbol = c4.text_input("Symbol", value="")


@st.cache_data(ttl=15)
def _journal(_engine, date_from, date_to, strategy, symbol):
    return queries.journal(_engine, date_from=date_from, date_to=date_to, strategy=strategy,
                           symbol=symbol or None)


df = _journal(engine, date_from.isoformat(), date_to.isoformat(), strategy, symbol)
st.dataframe(df, use_container_width=True)

st.download_button(
    "Download CSV", data=df.to_csv(index=False), file_name="journal.csv", mime="text/csv",
)
