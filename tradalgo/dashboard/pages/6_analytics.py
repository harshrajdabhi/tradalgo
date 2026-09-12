import streamlit as st

from tradalgo.dashboard import charts, queries
from tradalgo.dashboard.app import get_engine, get_settings

st.title("Analytics")

settings = get_settings()
engine = get_engine(settings)


@st.cache_data(ttl=15)
def _expectancy(_engine, group_col):
    return queries.expectancy_by(_engine, group_col)


@st.cache_data(ttl=15)
def _mfe_mae(_engine):
    return queries.mfe_mae_points(_engine)


@st.cache_data(ttl=15)
def _live_vs_backtest(_engine):
    return queries.live_vs_backtest_expectancy(_engine)


for group_col, label in (("strategy", "By strategy"), ("regime", "By regime"),
                          ("hour", "By hour of day"), ("symbol", "By symbol")):
    st.subheader(label)
    st.dataframe(_expectancy(engine, group_col), use_container_width=True)

st.subheader("MFE vs MAE")
st.plotly_chart(charts.mfe_mae_scatter(_mfe_mae(engine)), use_container_width=True)

st.subheader("Live vs backtest expectancy")
st.dataframe(_live_vs_backtest(engine), use_container_width=True)
