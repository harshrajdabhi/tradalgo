import pandas as pd
import streamlit as st

from tradalgo.dashboard import charts, queries
from tradalgo.dashboard.app import get_engine, get_settings
from tradalgo.data.candle_cache import CandleCache

st.title("Positions")

settings = get_settings()
engine = get_engine(settings)


@st.cache_data(ttl=15)
def _positions(_engine):
    return queries.positions(_engine)


@st.fragment(run_every=15)
def render() -> None:
    df = _positions(engine)
    st.dataframe(df, use_container_width=True)

    if df.empty:
        return

    labels = [f"{r.symbol} @ {r.entry_ts}" for r in df.itertuples()]
    choice = st.selectbox("Chart a position", options=range(len(df)), format_func=lambda i: labels[i])
    row = df.iloc[choice]

    day_candles = None
    try:
        cache = CandleCache(settings.paths.data_dir / "candles", provider=None)
        candles = cache.load(row["symbol"], "5m")
        if not candles.empty:
            target_date = pd.Timestamp(row["entry_ts"]).date()
            day_candles = candles[candles.index.date == target_date]
    except Exception:
        day_candles = None

    if day_candles is not None and not day_candles.empty:
        fig = charts.candlestick_with_levels(
            day_candles, entry=row.get("entry_price"), stop_loss=row.get("stop_loss"),
            target_2r=row.get("target_2r"), target_3r=row.get("target_3r"),
            title=f"{row['symbol']} {row['entry_ts']}",
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No cached candles for this position's day.")


render()
