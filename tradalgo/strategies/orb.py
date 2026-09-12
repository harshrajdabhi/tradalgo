"""Opening Range Breakout. Entry = trigger bar close (actionable right after the bar closes)."""
from dataclasses import dataclass

import pandas as pd

from tradalgo.indicators import opening_range
from tradalgo.strategies.base import MarketContext, Signal
from tradalgo.strategies.common import SESSION_OPEN, bounded_stop, last_atr, last_rvol, make_signal, today_bars


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
