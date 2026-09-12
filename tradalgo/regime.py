"""Stock / index regime classifier. Never uses volume (NIFTY50 index volume is 0)."""
import math

import pandas as pd

from tradalgo.indicators import adx, atr, ema
from tradalgo.strategies.base import Regime


def _session_range_expanded(c15: pd.DataFrame, range_mult: float, lookback_sessions: int) -> bool:
    dates = c15.index.date
    today = dates[-1]
    ranges = c15.groupby(dates).apply(lambda d: d["high"].max() - d["low"].min())
    prior = ranges[ranges.index < today].tail(lookback_sessions)
    if len(prior) < 3 or prior.mean() <= 0:
        return False
    return ranges.loc[today] > range_mult * prior.mean()


def _atr_pct_extreme(c5: pd.DataFrame, high_vol_pct: float, window: int, atr_period: int) -> bool:
    series = (atr(c5, atr_period) / c5["close"]).dropna().tail(window).to_numpy()
    if len(series) < 20:
        return False
    # strictly-below share, so a perfectly constant ATR% is never "top percentile"
    return float((series[:-1] < series[-1]).mean() * 100) >= high_vol_pct


def classify(candles_15m: pd.DataFrame, candles_5m: pd.DataFrame | None = None, adx_trend: float = 25.0,
             high_vol_pct: float = 90.0, range_mult: float = 1.5, range_lookback_sessions: int = 10,
             atr_pct_window: int = 375, adx_period: int = 14, ema_period: int = 20, atr_period: int = 14,
             min_bars: int = 40) -> Regime:
    """HIGH_VOL if today's 15m range so far > range_mult x mean full-session range of up to
    range_lookback_sessions prior sessions (needs >= 3), or if ATR14(5m)/close ranks in the top
    (100 - high_vol_pct)% of its last atr_pct_window bars (~5 sessions). HIGH_VOL wins over trend: ADX/EMA lag,
    so a trend reading during a volatility shock is unreliable and only ORB/gap setups are appropriate.
    Otherwise TREND_UP/DOWN when ADX14(15m) >= adx_trend with the DI and close-vs-EMA20 agreeing; else RANGE.
    RANGE when fewer than min_bars 15m bars exist."""
    if candles_15m is None or len(candles_15m) < min_bars:
        return Regime.RANGE
    if _session_range_expanded(candles_15m, range_mult, range_lookback_sessions):
        return Regime.HIGH_VOL
    if candles_5m is not None and len(candles_5m) and _atr_pct_extreme(candles_5m, high_vol_pct, atr_pct_window,
                                                                        atr_period):
        return Regime.HIGH_VOL
    d = adx(candles_15m, adx_period).iloc[-1]
    e = float(ema(candles_15m["close"], ema_period).iloc[-1])
    close = float(candles_15m["close"].iloc[-1])
    if any(not math.isfinite(x) for x in (d["adx"], d["plus_di"], d["minus_di"], e)) or d["adx"] < adx_trend:
        return Regime.RANGE
    if d["plus_di"] > d["minus_di"] and close > e:
        return Regime.TREND_UP
    if d["minus_di"] > d["plus_di"] and close < e:
        return Regime.TREND_DOWN
    return Regime.RANGE

