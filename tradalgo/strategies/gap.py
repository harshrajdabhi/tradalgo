"""Gap continuation / gap fade. Entry = trigger bar close."""
from dataclasses import dataclass

import pandas as pd

from tradalgo.indicators import opening_range, prev_day_hlc
from tradalgo.strategies.base import MarketContext, Signal
from tradalgo.strategies.orb import SESSION_OPEN, bounded_stop, last_atr, make_signal, today_bars


@dataclass(frozen=True)
class GapDetector:
    """gap_pct = today's first open vs previous completed daily close; needs |gap_pct| >= min_gap_pct.
    continuation: first 15m holds the gap (its close and far extreme stay beyond previous close) and the first
    later bar to close beyond the first-15m extreme in the gap direction fires; stop = other first-15m extreme.
    fade (counter-trend): the first later bar to close beyond the first-15m extreme against the gap fires;
    stop = the first-15m extreme on the gap side. Stops bounded to [min, max] x ATR14(5m)."""
    name: str = "gap"
    counter_trend: bool = False
    min_gap_pct: float = 0.5
    first_minutes: int = 15
    atr_period: int = 14
    min_stop_atr: float = 0.5
    max_stop_atr: float = 2.0

    def __call__(self, ctx: MarketContext) -> Signal | None:
        bars = today_bars(ctx)
        if bars is None:
            return None
        day = bars.index[-1].date()
        levels = prev_day_hlc(ctx.daily, day)
        atr5 = last_atr(ctx.candles_5m, self.atr_period)
        if levels is None or atr5 is None or bars.index[0].time() != SESSION_OPEN:
            return None
        prev_close = levels[2]
        gap_pct = (float(bars["open"].iloc[0]) - prev_close) / prev_close * 100
        if abs(gap_pct) < self.min_gap_pct:
            return None
        end = pd.Timestamp.combine(day, SESSION_OPEN).tz_localize(bars.index.tz) + pd.Timedelta(
            minutes=self.first_minutes)
        first, after = bars[bars.index < end], bars[bars.index >= end]
        if after.empty or len(first) < self.first_minutes // 5:
            return None
        f_high, f_low = opening_range(bars, day, self.first_minutes)
        f_close = float(first["close"].iloc[-1])
        c = float(after["close"].iloc[-1])
        earlier = after["close"].iloc[:-1]
        up = gap_pct > 0
        above = c > f_high and not (earlier > f_high).any()
        below = c < f_low and not (earlier < f_low).any()
        holds = (f_close > prev_close and f_low > prev_close) if up else (f_close < prev_close and f_high < prev_close)

        if (above if up else below) and holds:
            variant, counter = "continuation", False
            direction = "long" if up else "short"
        elif below if up else above:
            variant, counter = "fade", True
            direction = "short" if up else "long"
        else:
            return None
        structural = f_low if direction == "long" else f_high
        stop = bounded_stop(c, structural, atr5, direction, self.min_stop_atr, self.max_stop_atr)
        return make_signal(ctx, self.name, direction, c, stop, counter,
                           f"Gap {variant} {direction}: gap {gap_pct:+.2f}%, close beyond first-{self.first_minutes}m "
                           f"{'high' if c > f_high else 'low'}",
                           variant=variant, gap_pct=gap_pct, prev_close=prev_close, first_high=f_high,
                           first_low=f_low, atr5=atr5)


gap = GapDetector()
