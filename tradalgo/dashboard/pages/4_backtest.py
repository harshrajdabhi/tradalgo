import json
from datetime import date, datetime

import pandas as pd
import streamlit as st

from tradalgo.clock import IST
from tradalgo.dashboard import charts, controls, queries
from tradalgo.dashboard.app import get_engine, get_settings

st.title("Backtest")

settings = get_settings()
engine = get_engine(settings)

with st.form("queue_backtest"):
    c1, c2 = st.columns(2)
    date_from = c1.date_input("From", value=date.today())
    date_to = c2.date_input("To", value=date.today())
    universe = st.selectbox("Universe", options=["nifty50", "niftynext50", "both"])
    strategies = st.multiselect(
        "Strategies", options=["orb", "gap", "vwap", "pdhl", "pullback", "range_breakout"],
        default=["orb", "gap", "vwap", "pdhl", "pullback", "range_breakout"],
    )
    shortlist_size = st.slider("Shortlist size", min_value=5, max_value=7, value=settings.screener.shortlist_size)
    slippage_pct = st.number_input("Slippage %", min_value=0.0, value=settings.backtest.slippage_pct)
    max_risk_pct = st.number_input("Max risk %", min_value=0.0001, max_value=0.03,
                                   value=settings.capital.max_risk_pct)
    initial_capital = st.number_input("Initial capital", min_value=1.0, value=settings.capital.initial_capital)
    submitted = st.form_submit_button("Queue backtest")

if submitted:
    params = {
        "from": date_from.isoformat(), "to": date_to.isoformat(), "universe": universe,
        "strategies": strategies, "shortlist_size": shortlist_size, "slippage_pct": slippage_pct,
        "max_risk_pct": max_risk_pct, "initial_capital": initial_capital,
    }
    try:
        controls.queue_backtest(engine, params, datetime.now(IST))
        st.success("Backtest queued")
    except ValueError as exc:
        st.error(str(exc))


@st.cache_data(ttl=3)
def _runs(_engine):
    return queries.backtest_runs_list(_engine)


@st.fragment(run_every=3)
def render_runs() -> None:
    runs = _runs(engine)
    st.subheader("Runs")
    for row in runs.itertuples():
        cols = st.columns([1, 1, 1, 2, 1])
        cols[0].write(row.id)
        cols[1].write(row.status)
        cols[2].write(row.created_at)
        cols[3].progress(min(max(row.progress_pct or 0, 0), 100) / 100)
        if row.status in ("queued", "running"):
            if cols[4].button("Cancel", key=f"cancel_{row.id}"):
                controls.request_cancel_backtest(engine, row.id)
                st.cache_data.clear()
                st.rerun()
    st.dataframe(runs, use_container_width=True)


render_runs()

runs_df = _runs(engine)
if not runs_df.empty:
    run_id = st.selectbox("Select run", options=runs_df["id"].tolist())
    metrics = queries.backtest_run_metrics(engine, run_id)
    trades = queries.backtest_run_trades(engine, run_id)

    if metrics:
        tiles = st.columns(4)
        tiles[0].metric("Trades", metrics.get("trades"))
        tiles[1].metric("Win rate", metrics.get("win_rate"))
        tiles[2].metric("Expectancy R", metrics.get("expectancy_r"))
        tiles[3].metric("Max DD (R)", metrics.get("max_drawdown_r"))

    st.plotly_chart(charts.equity_curve(trades), use_container_width=True)
    st.plotly_chart(charts.r_multiple_histogram(trades), use_container_width=True)

    if metrics.get("by_strategy"):
        st.subheader("By strategy")
        st.dataframe(pd.DataFrame(metrics["by_strategy"]).T)
    if metrics.get("by_regime"):
        st.subheader("By regime")
        st.dataframe(pd.DataFrame(metrics["by_regime"]).T)

    st.subheader("Trades")
    st.dataframe(trades, use_container_width=True)

    st.subheader("Compare two runs")
    compare_ids = st.multiselect("Runs to compare", options=runs_df["id"].tolist(), max_selections=2)
    if len(compare_ids) == 2:
        cols = st.columns(2)
        for col, rid in zip(cols, compare_ids):
            m = queries.backtest_run_metrics(engine, rid)
            col.write(f"Run {rid}")
            col.json(m)
