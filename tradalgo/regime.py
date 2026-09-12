"""Stock / index regime classifier. Never uses volume (NIFTY50 index volume is 0)."""
import math

import numpy as np
import pandas as pd

from tradalgo.indicators import adx, ema, true_range
from tradalgo.strategies.base import Regime


def _up_to_same_time(df: pd.DataFrame) -> tuple[pd.DataFrame, np.ndarray]:
    """Rows at or before the last bar's time-of-day, so every session is compared over the same clock span."""
    t_now = df.index[-1].time()
    mask = np.array([t <= t_now for t in df.index.time])
    return df[mask], df.index.date[mask]


def _session_range_expanded(c15: pd.DataFrame, range_mult: float, lookback_sessions: int) -> bool:
    part, dates = _up_to_same_time(c15)
    today = c15.index[-1].date()
    ranges = part["high"].groupby(dates).max() - part["low"].groupby(dates).min()
    prior = ranges[ranges.index < today].tail(lookback_sessions)
    if len(prior) < 3 or prior.mean() <= 0:
        return False
    return ranges.loc[today] > range_mult * prior.mean()


def _tr_pct_extreme(c5: pd.DataFrame, high_vol_pct: float, lookback_sessions: int) -> bool:
    # time-of-day matched: the open is always more volatile, so rank today's mean TR% so far only against
    # prior sessions' mean TR% over the same clock span
    trp = true_range(c5) / c5["close"]
    mask_frame, dates = _up_to_same_time(trp.to_frame("v"))
    means = mask_frame["v"].groupby(dates).mean()
    today = c5.index[-1].date()
    prior = means[means.index < today].tail(lookback_sessions)
    if len(prior) < 3 or today not in means.index:
        return False
    # strictly-below share, so identical sessions are never "top percentile"
    return float((prior < means.loc[today]).mean() * 100) >= high_vol_pct


def classify(candles_15m: pd.DataFrame, candles_5m: pd.DataFrame | None = None, adx_trend: float = 25.0,
             high_vol_pct: float = 90.0, range_mult: float = 1.5, range_lookback_sessions: int = 10,
             vol_lookback_sessions: int = 20, adx_period: int = 14, ema_period: int = 20,
             min_bars: int = 40) -> Regime:
    """HIGH_VOL if today's 15m range so far > range_mult x mean range of up to range_lookback_sessions prior
    sessions measured up to the same time of day (needs >= 3), or if today's mean 5m true-range% so far ranks
    >= high_vol_pct percentile against up to vol_lookback_sessions prior sessions' mean over the same time span
    (needs >= 3). Both are time-of-day matched so the normal open volatility is not HIGH_VOL.
    HIGH_VOL wins over trend: ADX/EMA lag,
    so a trend reading during a volatility shock is unreliable and only ORB/gap setups are appropriate.
    Otherwise TREND_UP/DOWN when ADX14(15m) >= adx_trend with the DI and close-vs-EMA20 agreeing; else RANGE.
    RANGE when fewer than min_bars 15m bars exist."""
    if candles_15m is None or len(candles_15m) < min_bars:
        return Regime.RANGE
    if _session_range_expanded(candles_15m, range_mult, range_lookback_sessions):
        return Regime.HIGH_VOL
    if candles_5m is not None and len(candles_5m) and _tr_pct_extreme(candles_5m, high_vol_pct,
                                                                       vol_lookback_sessions):
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

