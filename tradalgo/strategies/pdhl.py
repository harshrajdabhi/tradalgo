"""Previous-day high/low breakout or rejection. Entry = trigger bar close."""
from dataclasses import dataclass

from tradalgo.indicators import prev_day_hlc
from tradalgo.strategies.base import MarketContext, Signal
from tradalgo.strategies.common import bounded_stop, last_atr, last_rvol, make_signal, today_bars


@dataclass(frozen=True)
class PdhlDetector:
    """breakout: first close today beyond PDH/PDL with RVOL >= min_rvol; stop = trigger bar opposite extreme.
    rejection (counter-trend): first bar today whose wick pierces PDH/PDL and closes back inside, wick >=
    min_wick_ratio of the bar range; stop = the wick extreme. Both bounded to [min, max] x ATR14(5m)."""
    name: str = "pdhl"
    counter_trend: bool = False
    min_rvol: float = 1.5
    min_wick_ratio: float = 0.5
    rvol_lookback_sessions: int = 10
    atr_period: int = 14
    min_stop_atr: float = 0.5
    max_stop_atr: float = 2.0

    def __call__(self, ctx: MarketContext) -> Signal | None:
        bars = today_bars(ctx)
        levels = prev_day_hlc(ctx.daily, bars.index[-1].date()) if bars is not None else None
        atr5 = last_atr(ctx.candles_5m, self.atr_period)
        if levels is None or atr5 is None:
            return None
        pdh, pdl, _ = levels
        o, h, l, c = (float(bars[k].iloc[-1]) for k in ("open", "high", "low", "close"))
        earlier = bars.iloc[:-1]
        feats = {"pdh": pdh, "pdl": pdl, "atr5": atr5}

        long_bo = c > pdh and not (earlier["close"] > pdh).any()
        short_bo = c < pdl and not (earlier["close"] < pdl).any()
        if long_bo or short_bo:
            rvol = last_rvol(ctx.candles_5m, self.rvol_lookback_sessions)
            if rvol < self.min_rvol:
                return None
            direction = "long" if long_bo else "short"
            stop = bounded_stop(c, l if long_bo else h, atr5, direction, self.min_stop_atr, self.max_stop_atr)
            return make_signal(ctx, self.name, direction, c, stop, False,
                               f"PD{'H' if long_bo else 'L'} breakout {direction}: first close beyond "
                               f"{pdh if long_bo else pdl:.2f} with RVOL {rvol:.1f}",
                               variant="breakout", rvol=rvol, **feats)

        rng = h - l
        if rng <= 0:
            return None
        e_rng = (earlier["high"] - earlier["low"]).where(lambda r: r > 0)
        e_body_hi = earlier[["open", "close"]].max(axis=1)
        e_body_lo = earlier[["open", "close"]].min(axis=1)
        # only an earlier *qualifying* rejection consumes the setup
        pierced_high = (earlier["high"] > pdh) & (earlier["close"] < pdh) & (
            (earlier["high"] - e_body_hi) / e_rng >= self.min_wick_ratio)
        pierced_low = (earlier["low"] < pdl) & (earlier["close"] > pdl) & (
            (e_body_lo - earlier["low"]) / e_rng >= self.min_wick_ratio)
        if h > pdh and c < pdh and (h - max(o, c)) / rng >= self.min_wick_ratio and not pierced_high.any():
            direction, structural, lvl = "short", h, "PDH"
        elif l < pdl and c > pdl and (min(o, c) - l) / rng >= self.min_wick_ratio and not pierced_low.any():
            direction, structural, lvl = "long", l, "PDL"
        else:
            return None
        stop = bounded_stop(c, structural, atr5, direction, self.min_stop_atr, self.max_stop_atr)
        return make_signal(ctx, self.name, direction, c, stop, True,
                           f"{lvl} rejection {direction}: wick beyond {lvl}, close back inside",
                           variant="rejection", **feats)


pdhl = PdhlDetector()
