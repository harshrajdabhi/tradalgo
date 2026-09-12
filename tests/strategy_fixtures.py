"""Synthetic candle builders for detector/regime tests. Index = IST candle start."""
from datetime import date, datetime, time, timedelta

import pandas as pd

from tradalgo.clock import IST
from tradalgo.strategies.base import MarketContext, Regime

TODAY = date(2026, 9, 15)  # Tuesday; 2026-09-14 is an NSE holiday
COLS = ["open", "high", "low", "close", "volume"]
AGG = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}


def at(hh: int, mm: int, day: date = TODAY) -> datetime:
    return datetime.combine(day, time(hh, mm), tzinfo=IST)


def prior_days(n: int, before: date = TODAY) -> list[date]:
    out, d = [], before
    while len(out) < n:
        d -= timedelta(days=1)
        if d.weekday() < 5 and d != date(2026, 9, 14):
            out.append(d)
    return sorted(out)


def frame(start: datetime, rows: list[tuple], minutes: int = 5) -> pd.DataFrame:
    idx = pd.DatetimeIndex([start + timedelta(minutes=minutes * i) for i in range(len(rows))], name="ts")
    return pd.DataFrame([list(map(float, r)) for r in rows], index=idx, columns=COLS)


def quiet_rows(n: int, price: float = 100.0, volume: float = 1000.0) -> list[tuple]:
    """Bars with true range exactly 1.0, so ATR14 of a quiet history is 1.0."""
    return [(price, price + 0.5, price - 0.5, price + (0.1 if i % 2 else -0.1), volume) for i in range(n)]


def history_5m(sessions: int = 12, price: float = 100.0, volume: float = 1000.0) -> pd.DataFrame:
    return pd.concat([frame(at(9, 15, d), quiet_rows(75, price, volume)) for d in prior_days(sessions)])


def with_today(today_rows: list[tuple], sessions: int = 12, price: float = 100.0) -> pd.DataFrame:
    return pd.concat([history_5m(sessions, price), frame(at(9, 15), today_rows)])


def resample_15m(c5: pd.DataFrame) -> pd.DataFrame:
    # label/closed left keeps candle-start indexing (09:15 bar = 09:15..09:30)
    return c5.resample("15min", label="left", closed="left").agg(AGG).dropna(subset=["open"])


def daily_from(c5: pd.DataFrame, before: date) -> pd.DataFrame:
    d = c5.groupby(c5.index.date).agg(AGG)
    d.index = pd.DatetimeIndex([pd.Timestamp(x).tz_localize(IST) for x in d.index], name="ts")
    return d[d.index.date < before]


def ctx_at(c5_full: pd.DataFrame, now: datetime, regime: Regime = Regime.RANGE,
           market_regime: Regime = Regime.RANGE, symbol: str = "TEST") -> MarketContext:
    """Slice to candles closed by `now`, exactly as live/backtest must."""
    c5 = c5_full[c5_full.index + pd.Timedelta(minutes=5) <= now]
    c15 = resample_15m(c5)
    c15 = c15[c15.index + pd.Timedelta(minutes=15) <= now]
    idx = c15.copy()
    idx["volume"] = 0.0
    return MarketContext(symbol, now, c5, c15, daily_from(c5_full, now.date()), idx, regime, market_regime)


def future_rows(n: int = 6, price: float = 150.0) -> list[tuple]:
    return [(price, price + 5, price - 5, price + 3, 99999.0)] * n


def append_future(c5: pd.DataFrame, n: int = 6, price: float = 150.0) -> pd.DataFrame:
    start = c5.index[-1] + timedelta(minutes=5)
    return pd.concat([c5, frame(start.to_pydatetime(), future_rows(n, price))])


def sessions_15m(days: list[date], price_fn, bars_per_day: int = 25, volume: float = 0.0,
                 last_day_bars: int | None = None) -> pd.DataFrame:
    """15m frame; price_fn(k) -> (open, high, low, close) for global bar number k."""
    parts, k = [], 0
    for j, d in enumerate(days):
        n = last_day_bars if (last_day_bars is not None and j == len(days) - 1) else bars_per_day
        rows = []
        for _ in range(n):
            rows.append((*price_fn(k), volume))
            k += 1
        parts.append(frame(at(9, 15, d), rows, minutes=15))
    return pd.concat(parts)
