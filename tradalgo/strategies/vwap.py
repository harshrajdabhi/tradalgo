"""VWAP continuation / reclaim / rejection. Entry = trigger bar close."""
from dataclasses import dataclass

import numpy as np

from tradalgo.indicators import session_vwap
from tradalgo.strategies.base import MarketContext, Regime, Signal
from tradalgo.strategies.orb import bounded_stop, last_atr, make_signal, today_bars


@dataclass(frozen=True)
class VwapDetector:
    """Checked in order, first match wins (all on today's session VWAP, stops bounded to ATR14(5m) limits):
    continuation (TREND_UP long / TREND_DOWN short): previous bar closed on the trend side without touching
      VWAP*(1±touch_tol); trigger bar's low (high) touches it and closes back on the trend side; stop = bar extreme.
    reclaim: >= reclaim_bars consecutive closes on the other side, trigger closes back across; stop = extreme
      of that stretch including the trigger bar.
    rejection (counter-trend): price moved toward VWAP (close[-2] vs close[-2-move_lookback]); the previous bar
      stayed fully on its side, the trigger pierces VWAP and closes back with wick >= min_wick_ratio of range;
      stop = wick extreme. Direction is against the recent move."""
    name: str = "vwap"
    counter_trend: bool = False
    touch_tol: float = 0.001
    reclaim_bars: int = 3
    min_wick_ratio: float = 0.5
    move_lookback: int = 2
    atr_period: int = 14
    min_stop_atr: float = 0.5
    max_stop_atr: float = 2.0

    def __call__(self, ctx: MarketContext) -> Signal | None:
        today = today_bars(ctx)
        atr5 = last_atr(ctx.candles_5m, self.atr_period)
        if today is None or atr5 is None or len(today) < 2:
            return None
        n = len(today)
        vw = session_vwap(ctx.candles_5m).iloc[-n:].to_numpy()
        if np.isnan(vw).any():
            return None
        o, h, l, c = (today[k].to_numpy() for k in ("open", "high", "low", "close"))
        v = vw[-1]
        found = self._continuation(ctx, h, l, c, vw) or self._reclaim(h, l, c, vw) or \
            self._rejection(o, h, l, c, vw)
        if found is None:
            return None
        variant, direction, structural = found
        counter = variant == "rejection"
        stop = bounded_stop(float(c[-1]), structural, atr5, direction, self.min_stop_atr, self.max_stop_atr)
        return make_signal(ctx, self.name, direction, float(c[-1]), stop, counter,
                           f"VWAP {variant} {direction}: close {c[-1]:.2f} vs VWAP {v:.2f}",
                           variant=variant, vwap=float(v), atr5=atr5)

    def _continuation(self, ctx, h, l, c, vw):
        up, dn = 1 + self.touch_tol, 1 - self.touch_tol
        if ctx.regime == Regime.TREND_UP and c[-2] > vw[-2] and l[-2] > vw[-2] * up \
                and l[-1] <= vw[-1] * up and c[-1] > vw[-1]:
            return "continuation", "long", float(l[-1])
        if ctx.regime == Regime.TREND_DOWN and c[-2] < vw[-2] and h[-2] < vw[-2] * dn \
                and h[-1] >= vw[-1] * dn and c[-1] < vw[-1]:
            return "continuation", "short", float(h[-1])
        return None

    def _reclaim(self, h, l, c, vw):
        k = self.reclaim_bars
        if len(c) < k + 1:
            return None
        prev_c, prev_v = c[-1 - k:-1], vw[-1 - k:-1]
        if c[-1] > vw[-1] and (prev_c < prev_v).all():
            return "reclaim", "long", float(l[-1 - k:].min())
        if c[-1] < vw[-1] and (prev_c > prev_v).all():
            return "reclaim", "short", float(h[-1 - k:].max())
        return None

    def _rejection(self, o, h, l, c, vw):
        if len(c) < self.move_lookback + 2:
            return None
        rng = h[-1] - l[-1]
        if rng <= 0:
            return None
        rising = c[-2] > c[-2 - self.move_lookback]
        falling = c[-2] < c[-2 - self.move_lookback]
        if rising and h[-2] < vw[-2] and h[-1] > vw[-1] and c[-1] < vw[-1] \
                and (h[-1] - max(o[-1], c[-1])) / rng >= self.min_wick_ratio:
            return "rejection", "short", float(h[-1])
        if falling and l[-2] > vw[-2] and l[-1] < vw[-1] and c[-1] > vw[-1] \
                and (min(o[-1], c[-1]) - l[-1]) / rng >= self.min_wick_ratio:
            return "rejection", "long", float(l[-1])
        return None


vwap = VwapDetector()
