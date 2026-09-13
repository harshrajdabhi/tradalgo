from dataclasses import replace

from tradalgo.clock import MarketCalendar
from tradalgo.config import Settings
from tradalgo.strategies import gap, orb, pdhl, pullback, range_breakout, vwap
from tradalgo.strategies.base import Detector, MarketContext, Regime, Signal

_MODULES = (orb, vwap, pdhl, pullback, range_breakout, gap)
ALL_DETECTORS: dict[str, Detector] = {m.__name__.rsplit(".", 1)[1]: getattr(m, m.__name__.rsplit(".", 1)[1])
                                      for m in _MODULES}
PARAM_DEFAULTS: dict[str, dict] = {m.__name__.rsplit(".", 1)[1]: m.DEFAULTS for m in _MODULES}

_TREND = {"orb", "vwap", "pdhl", "pullback", "gap"}
REGIME_STRATEGIES: dict[Regime, set[str]] = {
    Regime.TREND_UP: _TREND,
    Regime.TREND_DOWN: _TREND,
    Regime.RANGE: {"vwap", "range_breakout", "pdhl"},
    Regime.HIGH_VOL: {"orb", "gap"},
}


def check_params(name: str, params: dict) -> dict:
    """params coerced to each default's type; unknown keys raise so a sweep-grid typo fails loudly."""
    defaults = PARAM_DEFAULTS[name]
    out = {}
    for key, value in params.items():
        if key not in defaults:
            raise ValueError(f"strategy {name}: unknown param {key!r} (known: {sorted(defaults)})")
        default = defaults[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"strategy {name}: param {key!r} must be a number, got {value!r}")
        if isinstance(default, int):
            if float(value) != int(value):
                raise ValueError(f"strategy {name}: param {key!r} must be an integer, got {value!r}")
            value = int(value)
        else:
            value = float(value)
        out[key] = value
    return out


def configured_detector(name: str, settings: Settings) -> Detector:
    pm = settings.position_management
    params = check_params(name, settings.strategies[name].params)
    # read as {**DEFAULTS, **params}: unset keys keep the detector's own defaults
    return replace(ALL_DETECTORS[name], min_stop_atr=pm.stop_atr_min, max_stop_atr=pm.stop_atr_max,
                   **{**PARAM_DEFAULTS[name], **params})


def market_alignment_ok(signal: Signal) -> bool:
    """Block longs when the market or the stock is TREND_DOWN (shorts: TREND_UP), unless counter-trend."""
    if signal.counter_trend:
        return True
    against = Regime.TREND_DOWN if signal.direction == "long" else Regime.TREND_UP
    return against not in (signal.market_regime, signal.regime)


def detect_all(ctx: MarketContext, settings: Settings, calendar: MarketCalendar) -> list[Signal]:
    out = []
    for name in ALL_DETECTORS:
        cfg = settings.strategies.get(name)
        if cfg is None or not cfg.enabled or not calendar.can_enter(ctx.now, cfg):
            continue
        if name not in REGIME_STRATEGIES[ctx.regime]:
            continue
        signal = configured_detector(name, settings)(ctx)
        if signal is not None and market_alignment_ok(signal):
            out.append(signal)
    return out
