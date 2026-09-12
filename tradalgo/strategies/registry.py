from tradalgo.clock import MarketCalendar
from tradalgo.config import Settings
from tradalgo.strategies.base import Detector, MarketContext, Regime, Signal
from tradalgo.strategies.gap import gap
from tradalgo.strategies.orb import orb
from tradalgo.strategies.pdhl import pdhl
from tradalgo.strategies.pullback import pullback
from tradalgo.strategies.range_breakout import range_breakout
from tradalgo.strategies.vwap import vwap

ALL_DETECTORS: dict[str, Detector] = {d.name: d for d in (orb, vwap, pdhl, pullback, range_breakout, gap)}

_TREND = {"orb", "vwap", "pdhl", "pullback", "gap"}
REGIME_STRATEGIES: dict[Regime, set[str]] = {
    Regime.TREND_UP: _TREND,
    Regime.TREND_DOWN: _TREND,
    Regime.RANGE: {"vwap", "range_breakout", "pdhl"},
    Regime.HIGH_VOL: {"orb", "gap"},
}


def market_alignment_ok(signal: Signal) -> bool:
    """Block longs when the market or the stock is TREND_DOWN (shorts: TREND_UP), unless counter-trend."""
    if signal.counter_trend:
        return True
    against = Regime.TREND_DOWN if signal.direction == "long" else Regime.TREND_UP
    return against not in (signal.market_regime, signal.regime)


def detect_all(ctx: MarketContext, settings: Settings, calendar: MarketCalendar) -> list[Signal]:
    out = []
    for name, detector in ALL_DETECTORS.items():
        cfg = settings.strategies.get(name)
        if cfg is None or not cfg.enabled or not calendar.can_enter(ctx.now, cfg):
            continue
        if name not in REGIME_STRATEGIES[ctx.regime]:
            continue
        signal = detector(ctx)
        if signal is not None and market_alignment_ok(signal):
            out.append(signal)
    return out
