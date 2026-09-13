"""Intraday consolidation breakout. Entry = trigger bar close."""
from dataclasses import dataclass

from tradalgo.strategies.base import MarketContext, Signal
from tradalgo.strategies.common import bounded_stop, last_atr, last_rvol, make_signal, today_bars, tunable_defaults


@dataclass(frozen=True)
class RangeBreakoutDetector:
    """Box = the `bars` closed bars before the trigger (today only). Box is a consolidation when
    high - low <= range_atr_mult * k * ATR14(5m); k widens the 0.8 x ATR per-bar-ish budget over a multi-bar
    window (default 0.8 * 2.0 = 1.6 ATR across 6 bars). Trigger closes outside the box with RVOL >= min_rvol.
    Stop = opposite box side, bounded. At most one signal per box: see _box_contains_breakout."""
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
        if today is None or atr5 is None or len(today) < self.bars + 1:
            return None
        box = today.iloc[-1 - self.bars:-1]
        hi, lo = float(box["high"].max()), float(box["low"].min())
        if hi - lo > self.range_atr_mult * self.k * atr5:
            return None
        if self._box_contains_breakout(today):
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

    def _box_contains_breakout(self, today) -> bool:
        """True if any box bar (with a full window before it today) closed outside the `bars` bars before it.
        A box holding an earlier breakout bar is the same, already-broken setup; this blocks the trigger's next bar
        and a failed-breakout retest from firing again, while a fresh box of inside bars can still fire."""
        h, l, c = (today[k].to_numpy() for k in ("high", "low", "close"))
        n = len(today)
        for j in range(max(self.bars, n - 1 - self.bars), n - 1):
            if not (l[j - self.bars:j].min() <= c[j] <= h[j - self.bars:j].max()):
                return True
        return False


range_breakout = RangeBreakoutDetector()
DEFAULTS: dict = tunable_defaults(RangeBreakoutDetector)
