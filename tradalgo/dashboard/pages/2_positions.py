from datetime import datetime

import pandas as pd
import streamlit as st

from tradalgo.clock import IST
from tradalgo.dashboard import charts, queries
from tradalgo.dashboard.app import get_engine, get_settings
from tradalgo.data.candle_cache import CandleCache

st.title("Positions")

settings = get_settings()
engine = get_engine(settings)


@st.cache_data(ttl=15)
def _positions(_engine):
    return queries.trade_positions(_engine)


@st.cache_data(ttl=15)
def _alerts(_engine):
    return queries.alerts_log(_engine)


def _awaiting_reply(alerts: pd.DataFrame, signal_id) -> bool:
    """A signal's entry alert is awaiting the user's reply: sent, no user action yet,
    and not past its valid_until. Only then does the chart use amber for its levels.
    """
    if alerts.empty:
        return False
    rows = alerts[(alerts["signal_id"] == signal_id) & (alerts["alert_type"] == "entry")
                  & (alerts["status"] == "sent") & alerts["user_action"].isna()]
    if rows.empty:
        return False
    now = datetime.now(IST)
    for valid_until in rows["valid_until"]:
        if valid_until is None:
            return True
        try:
            if pd.Timestamp(valid_until) >= now:
                return True
        except (TypeError, ValueError):
            return True
    return False


@st.fragment(run_every=15)
def render() -> None:
    df = _positions(engine)
    if df.empty:
        st.info("No trades yet. They will appear here once an alert is marked Taken.")
        return
    st.dataframe(df, use_container_width=True)

    labels = [f"{r.symbol} @ {r.entry_ts}" for r in df.itertuples()]
    choice = st.selectbox("Chart a position", options=range(len(df)), format_func=lambda i: labels[i])
    row = df.iloc[choice]

    # CandleCache.load returns an empty frame when nothing is cached for this symbol yet —
    # that is the only expected "no data" case. Any other error (bad parquet, etc.) should surface.
    cache = CandleCache(settings.paths.data_dir / "candles", provider=None)
    candles = cache.load(row["symbol"], "5m")
    day_candles = None
    if not candles.empty:
        target_date = pd.Timestamp(row["entry_ts"]).date()
        day_candles = candles[candles.index.date == target_date]

    if day_candles is not None and not day_candles.empty:
        awaiting = _awaiting_reply(_alerts(engine), row.get("signal_id"))
        fig = charts.candlestick_with_levels(
            day_candles, entry=row.get("entry_price"), stop_loss=row.get("stop_loss"),
            target_2r=row.get("target_2r"), target_3r=row.get("target_3r"),
            title=f"{row['symbol']} {row['entry_ts']}", awaiting_reply=awaiting,
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No cached candles for this position's day yet.")


render()
