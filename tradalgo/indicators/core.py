import numpy as np
import pandas as pd


def _wilder(values: pd.Series, period: int) -> pd.Series:
    """Wilder smoothing seeded with the simple mean of the first `period` valid values."""
    arr = values.to_numpy(dtype=float)
    out = np.full(len(arr), np.nan)
    valid = np.flatnonzero(~np.isnan(arr))
    if len(valid) < period:
        return pd.Series(out, index=values.index)
    start = valid[period - 1]
    out[start] = np.nanmean(arr[valid[0]:start + 1])
    for i in range(start + 1, len(arr)):
        out[i] = (out[i - 1] * (period - 1) + arr[i]) / period
    return pd.Series(out, index=values.index)


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    return pd.concat([
        df["high"] - df["low"], (df["high"] - prev_close).abs(), (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    return _wilder(true_range(df), period)


def ema(series: pd.Series, period: int) -> pd.Series:
    arr = series.to_numpy(dtype=float)
    out = np.full(len(arr), np.nan)
    if len(arr) < period:
        return pd.Series(out, index=series.index)
    alpha = 2 / (period + 1)
    out[period - 1] = arr[:period].mean()
    for i in range(period, len(arr)):
        out[i] = alpha * arr[i] + (1 - alpha) * out[i - 1]
    return pd.Series(out, index=series.index)


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    diff = series.diff()
    avg_gain = _wilder(diff.clip(lower=0), period)
    avg_loss = _wilder((-diff).clip(lower=0), period)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = 100 - 100 / (1 + avg_gain / avg_loss)
    out = out.where(avg_loss != 0, 100.0).where((avg_loss != 0) | (avg_gain != 0), 50.0)
    return out.where(avg_gain.notna())


def adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = up.where((up > down) & (up > 0), 0.0).where(up.notna())
    minus_dm = down.where((down > up) & (down > 0), 0.0).where(down.notna())
    tr = true_range(df).where(df["close"].shift(1).notna())
    smooth_tr = _wilder(tr, period)
    plus_di = 100 * _wilder(plus_dm, period) / smooth_tr
    minus_di = 100 * _wilder(minus_dm, period) / smooth_tr
    di_sum = plus_di + minus_di
    dx = (100 * (plus_di - minus_di).abs() / di_sum).where(di_sum != 0, 0.0).where(di_sum.notna())
    return pd.DataFrame({"adx": _wilder(dx, period), "plus_di": plus_di, "minus_di": minus_di})


def session_vwap(candles: pd.DataFrame) -> pd.Series:
    typical = (candles["high"] + candles["low"] + candles["close"]) / 3
    by_day = candles.index.date
    pv = (typical * candles["volume"]).groupby(by_day).cumsum()
    vol = candles["volume"].groupby(by_day).cumsum()
    return pv / vol


def intraday_relative_volume(candles: pd.DataFrame, lookback_sessions: int = 10) -> pd.Series:
    """Bar volume / mean volume of the same time-of-day bar over the previous `lookback_sessions` sessions."""
    vol = candles["volume"]
    baseline = vol.groupby(candles.index.time).transform(
        lambda s: s.shift(1).rolling(lookback_sessions, min_periods=1).mean())
    return vol / baseline


def daily_relative_volume(daily: pd.DataFrame, lookback: int = 20) -> float:
    prior = daily["volume"].iloc[-lookback - 1:-1]
    if len(prior) < lookback or prior.mean() == 0:
        return float("nan")
    return float(daily["volume"].iloc[-1] / prior.mean())


def rolling_percentile(series: pd.Series, window: int, min_periods: int = 20) -> pd.Series:
    """Percent (0..100) of values in the trailing window that are <= the current value."""
    return series.rolling(window, min_periods=min_periods).apply(
        lambda w: np.nan if np.isnan(w[-1]) else (w[~np.isnan(w)] <= w[-1]).mean() * 100, raw=True)


def realized_vol_percentile(daily: pd.DataFrame, window: int = 20, lookback: int = 250) -> pd.Series:
    vol = np.log(daily["close"]).diff().rolling(window).std()
    return rolling_percentile(vol, lookback)


def atr_pct(daily: pd.DataFrame, period: int = 14) -> pd.Series:
    return atr(daily, period) / daily["close"]


def atr_pct_percentile(daily: pd.DataFrame, period: int = 14, lookback: int = 250) -> pd.Series:
    return rolling_percentile(atr_pct(daily, period), lookback)


def bb_width(df: pd.DataFrame, period: int = 20, k: float = 2.0) -> pd.Series:
    mid = df["close"].rolling(period).mean()
    return 2 * k * df["close"].rolling(period).std(ddof=0) / mid


def bb_width_percentile(df: pd.DataFrame, period: int = 20, lookback: int = 120) -> pd.Series:
    return rolling_percentile(bb_width(df, period), lookback)


def nr7(df: pd.DataFrame) -> pd.Series:
    rng = df["high"] - df["low"]
    return (rng <= rng.rolling(7).min()) & rng.rolling(7).min().notna()
