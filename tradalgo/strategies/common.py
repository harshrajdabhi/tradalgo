"""Helpers shared by all detectors."""
import math
from datetime import time

import pandas as pd

from tradalgo.clock import to_ist
from tradalgo.indicators import atr, intraday_relative_volume
from tradalgo.strategies.base import Direction, MarketContext, Signal

SESSION_OPEN = time(9, 15)


def today_bars(ctx: MarketContext) -> pd.DataFrame | None:
    """Today's closed 5m bars, or None if the last closed bar is not from today."""
    c = ctx.candles_5m
    day = to_ist(ctx.now).date()
    if c.empty or c.index[-1].date() != day:
        return None
    return c[c.index.date == day]


def last_atr(candles: pd.DataFrame, period: int = 14) -> float | None:
    v = float(atr(candles, period).iloc[-1]) if len(candles) else float("nan")
    return v if math.isfinite(v) and v > 0 else None


def last_rvol(candles: pd.DataFrame, lookback_sessions: int = 10) -> float:
    v = float(intraday_relative_volume(candles, lookback_sessions).iloc[-1])
    return v if math.isfinite(v) else 0.0


def bounded_stop(entry: float, structural: float, atr_value: float, direction: Direction,
                 min_atr: float = 0.5, max_atr: float = 2.0) -> float:
    dist = entry - structural if direction == "long" else structural - entry
    dist = min(max(dist, min_atr * atr_value), max_atr * atr_value)
    return entry - dist if direction == "long" else entry + dist


def make_signal(ctx: MarketContext, strategy: str, direction: Direction, entry: float, stop: float,
                counter_trend: bool, reason: str, **features) -> Signal:
    ts = ctx.candles_5m.index[-1].to_pydatetime()
    return Signal(ctx.symbol, strategy, direction, ts, float(entry), float(stop), ctx.regime, ctx.market_regime,
                  counter_trend, reason, features)
