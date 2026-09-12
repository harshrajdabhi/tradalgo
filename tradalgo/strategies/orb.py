"""Opening Range Breakout, plus small helpers shared by all detectors.

Entry = trigger bar close (the price a manual trader can act on right after the bar closes).
"""
import math
from dataclasses import dataclass
from datetime import time

import pandas as pd

from tradalgo.clock import to_ist
from tradalgo.indicators import atr, intraday_relative_volume, opening_range
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


@dataclass(frozen=True)
class OrbDetector:
    """First 5m close beyond the opening range today with RVOL >= min_rvol; stop = opposite OR side (bounded).

    If the first close beyond a side lacks volume, that side does not fire later today (first-close rule).
    """
    name: str = "orb"
    counter_trend: bool = False
    or_minutes: int = 15
    min_rvol: float = 1.5
    rvol_lookback_sessions: int = 10
    atr_period: int = 14
    min_stop_atr: float = 0.5
    max_stop_atr: float = 2.0

    def __call__(self, ctx: MarketContext) -> Signal | None:
        bars = today_bars(ctx)
        if bars is None:
            return None
        day = bars.index[-1].date()
        or_end = pd.Timestamp.combine(day, SESSION_OPEN).tz_localize(bars.index.tz) + pd.Timedelta(
            minutes=self.or_minutes)
        after = bars[bars.index >= or_end]
        if after.empty or len(bars) - len(after) < self.or_minutes // 5:
            return None
        or_hl = opening_range(bars, day, self.or_minutes)
        atr5 = last_atr(ctx.candles_5m, self.atr_period)
        if or_hl is None or atr5 is None:
            return None
        or_high, or_low = or_hl
        close = float(after["close"].iloc[-1])
        earlier = after["close"].iloc[:-1]
        if close > or_high and not (earlier > or_high).any():
            direction, structural = "long", or_low
        elif close < or_low and not (earlier < or_low).any():
            direction, structural = "short", or_high
        else:
            return None
        rvol = last_rvol(ctx.candles_5m, self.rvol_lookback_sessions)
        if rvol < self.min_rvol:
            return None
        stop = bounded_stop(close, structural, atr5, direction, self.min_stop_atr, self.max_stop_atr)
        side = "high" if direction == "long" else "low"
        return make_signal(ctx, self.name, direction, close, stop, False,
                           f"ORB {direction}: first close beyond {self.or_minutes}m OR {side} with RVOL {rvol:.1f}",
                           rvol=rvol, atr5=atr5, or_high=or_high, or_low=or_low)


orb = OrbDetector()
