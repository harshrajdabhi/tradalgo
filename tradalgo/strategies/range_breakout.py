"""Intraday consolidation breakout. Entry = trigger bar close."""
from dataclasses import dataclass

from tradalgo.strategies.base import MarketContext, Signal
from tradalgo.strategies.orb import bounded_stop, last_atr, last_rvol, make_signal, today_bars


@dataclass(frozen=True)
class RangeBreakoutDetector:
    """Box = the `bars` closed bars before the trigger (today only). Box is a consolidation when
    high - low <= range_atr_mult * k * ATR14(5m); k widens the 0.8 x ATR per-bar-ish budget over a multi-bar
    window (default 0.8 * 2.0 = 1.6 ATR across 6 bars). Trigger closes outside the box with RVOL >= min_rvol.
    Stop = opposite box side, bounded. No re-fire: the bar before the trigger must itself have closed inside the
    box formed by the `bars` bars before it (the trigger bar breaks that on the next cycle)."""
    name: str = "range_breakout"
    counter_trend: bool = False
    bars: int = 6
    range_atr_mult: float = 0.8
    k: float = 2.0
    min_rvol: float = 1.5
    rvol_lookback_sessions: int = 10
    atr_period: int = 14
    min_stop_atr: float = 0.5
    max_stop_atr: float = 2.0

    def __call__(self, ctx: MarketContext) -> Signal | None:
        today = today_bars(ctx)
        atr5 = last_atr(ctx.candles_5m, self.atr_period)
        if today is None or atr5 is None or len(today) < self.bars + 2:
            return None
        box = today.iloc[-1 - self.bars:-1]
        hi, lo = float(box["high"].max()), float(box["low"].min())
        if hi - lo > self.range_atr_mult * self.k * atr5:
            return None
        prior = today.iloc[-2 - self.bars:-2]
        prev_close = float(today["close"].iloc[-2])
        if not (prior["low"].min() <= prev_close <= prior["high"].max()):
            return None
        c = float(today["close"].iloc[-1])
        if c > hi:
            direction, structural = "long", lo
        elif c < lo:
            direction, structural = "short", hi
        else:
            return None
        rvol = last_rvol(ctx.candles_5m, self.rvol_lookback_sessions)
        if rvol < self.min_rvol:
            return None
        stop = bounded_stop(c, structural, atr5, direction, self.min_stop_atr, self.max_stop_atr)
        return make_signal(ctx, self.name, direction, c, stop, False,
                           f"Range breakout {direction}: close outside {self.bars}-bar box "
                           f"{lo:.2f}-{hi:.2f} with RVOL {rvol:.1f}",
                           rvol=rvol, atr5=atr5, range_high=hi, range_low=lo)


range_breakout = RangeBreakoutDetector()
