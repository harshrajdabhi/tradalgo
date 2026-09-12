"""Momentum pullback after a strong expansion. Entry = trigger bar close."""
from dataclasses import dataclass

import numpy as np

from tradalgo.indicators import ema
from tradalgo.strategies.base import MarketContext, Signal
from tradalgo.strategies.orb import bounded_stop, last_atr, make_signal, today_bars


@dataclass(frozen=True)
class PullbackDetector:
    """Long (short mirrored): the session extreme before the trigger (peak) is >= expansion_atr x ATR14(5m)
    above today's open; the bars after the peak (at least one) pull back so some low reaches
    EMA9 * (1 + touch_tol) while every close holds above EMA20; the trigger bar closes above the previous bar's
    high, and no pullback bar did so before (stateless no-re-fire). Stop = pullback swing low (incl. trigger)."""
    name: str = "pullback"
    counter_trend: bool = False
    expansion_atr: float = 2.0
    fast_ema: int = 9
    slow_ema: int = 20
    touch_tol: float = 0.002
    atr_period: int = 14
    min_stop_atr: float = 0.5
    max_stop_atr: float = 2.0

    def __call__(self, ctx: MarketContext) -> Signal | None:
        today = today_bars(ctx)
        atr5 = last_atr(ctx.candles_5m, self.atr_period)
        if today is None or atr5 is None or len(today) < 3:
            return None
        n = len(today)
        fast = ema(ctx.candles_5m["close"], self.fast_ema).iloc[-n:].to_numpy()
        slow = ema(ctx.candles_5m["close"], self.slow_ema).iloc[-n:].to_numpy()
        o, h, l, c = (today[k].to_numpy() for k in ("open", "high", "low", "close"))
        if np.isnan(fast).any() or np.isnan(slow).any():
            return None
        day_open = o[0]
        for direction in ("long", "short"):
            sign = 1 if direction == "long" else -1
            ext = h[:-1] if sign == 1 else -l[:-1]
            p = int(np.argmax(ext))
            if p >= n - 2 or sign * ((h[p] if sign == 1 else l[p]) - day_open) < self.expansion_atr * atr5:
                continue
            seg = slice(p + 1, n - 1)
            if sign == 1:
                touched = (l[seg] <= fast[seg] * (1 + self.touch_tol)).any()
                held = (c[seg] >= slow[seg]).all()
                early_break = (c[p + 2:n - 1] > h[p + 1:n - 2]).any()
                trigger = c[-1] > h[-2]
                structural = float(l[p + 1:].min())
            else:
                touched = (h[seg] >= fast[seg] * (1 - self.touch_tol)).any()
                held = (c[seg] <= slow[seg]).all()
                early_break = (c[p + 2:n - 1] < l[p + 1:n - 2]).any()
                trigger = c[-1] < l[-2]
                structural = float(h[p + 1:].max())
            if not (touched and held and trigger) or early_break:
                continue
            entry = float(c[-1])
            stop = bounded_stop(entry, structural, atr5, direction, self.min_stop_atr, self.max_stop_atr)
            move = abs((h[p] if sign == 1 else l[p]) - day_open)
            return make_signal(ctx, self.name, direction, entry, stop, False,
                               f"Pullback {direction}: {move / atr5:.1f} ATR expansion, held EMA{self.slow_ema}, "
                               f"broke prior bar {'high' if sign == 1 else 'low'}",
                               atr5=atr5, expansion_atr=move / atr5, ema_fast=float(fast[-1]),
                               ema_slow=float(slow[-1]))
        return None


pullback = PullbackDetector()
