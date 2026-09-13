from datetime import datetime, timedelta

import streamlit as st

from tradalgo.clock import IST
from tradalgo.dashboard import controls, queries, theme
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


@st.cache_data(ttl=15)
def _alerts_today(_engine, d):
    return queries.alerts_log(_engine, trade_date=d)


@st.cache_data(ttl=15)
def _open_trades(_engine):
    df = queries.trade_positions(_engine)
    return df[df["exit_ts"].isna()] if not df.empty else df


def _render_now_strip() -> None:
    kill_on = controls.kill_switch_active(settings.paths.data_dir)
    alerts = _alerts_today(engine, trade_date.isoformat())
    failed = alerts[alerts["status"] == "failed"].to_dict("records") if not alerts.empty else []
    awaiting = []
    if not alerts.empty:
        pending = alerts[(alerts["alert_type"] == "entry") & alerts["user_action"].isna()
                         & (alerts["status"] != "failed")]
        for row in pending.to_dict("records"):
            awaiting.append({"symbol": row["symbol"], "text": row.get("text") or "",
                             "valid_until": row.get("valid_until") or "unknown"})
    open_trades = _open_trades(engine).to_dict("records")
    next_check = (datetime.now(IST) + timedelta(minutes=15)).strftime("%H:%M")

    state = theme.now_strip_state(
        kill_switch_on=kill_on, failed_alerts=failed, awaiting_alerts=awaiting,
        open_trades=open_trades, next_check=next_check,
    )
    css_class = "now-strip now-strip--quiet" if state.quiet else "now-strip"
    st.markdown(f'<div class="{css_class}">{state.headline}</div>', unsafe_allow_html=True)


@st.fragment(run_every=15)
def render() -> None:
    _render_now_strip()

    st.subheader("Shortlist")
    shortlist = _shortlist(engine, trade_date.isoformat())
    if shortlist.empty:
        st.info("No picks for today yet. The screener runs at 07:00; run `tradalgo screen` to run it now.")
    else:
        st.dataframe(shortlist, use_container_width=True)

    st.subheader("Signals and decisions")
    signals = _signals(engine, trade_date.isoformat())
    if not signals.empty:
        for col in ("regime", "market_regime"):
            if col in signals.columns:
                st.caption(f"{col}: {sorted(signals[col].dropna().unique().tolist())}")
        st.dataframe(signals, use_container_width=True)
    else:
        st.info("No signals for this date yet.")


render()
