from datetime import date, time, timedelta

import numpy as np
import pandas as pd


def swings(df: pd.DataFrame, n: int = 2) -> pd.DataFrame:
    """Fractal swings reported on the bar where they become confirmed (n bars after the pivot), never earlier."""
    window = 2 * n + 1
    pivot_high = df["high"].shift(n)
    pivot_low = df["low"].shift(n)
    is_high = pivot_high == df["high"].rolling(window).max()
    is_low = pivot_low == df["low"].rolling(window).min()
    return pd.DataFrame({
        "swing_high": pivot_high.where(is_high),
        "swing_low": pivot_low.where(is_low),
    }, index=df.index)


def _before(daily: pd.DataFrame, as_of: date) -> pd.DataFrame:
    return daily[daily.index.date < as_of]


def prev_day_hlc(daily: pd.DataFrame, as_of: date) -> tuple[float, float, float] | None:
    prior = _before(daily, as_of)
    if prior.empty:
        return None
    row = prior.iloc[-1]
    return float(row["high"]), float(row["low"]), float(row["close"])


def prev_week_hl(daily: pd.DataFrame, as_of: date) -> tuple[float, float] | None:
    week_start = as_of - timedelta(days=as_of.weekday())
    prev_start = week_start - timedelta(days=7)
    dates = daily.index.date
    week = daily[(dates >= prev_start) & (dates < week_start)]
    if week.empty:
        return None
    return float(week["high"].max()), float(week["low"].min())


def opening_range(candles: pd.DataFrame, day: date, minutes: int = 15,
                  session_open: time = time(9, 15)) -> tuple[float, float] | None:
    start = pd.Timestamp.combine(day, session_open).tz_localize(candles.index.tz)
    bars = candles[(candles.index >= start) & (candles.index < start + pd.Timedelta(minutes=minutes))]
    if bars.empty:
        return None
    return float(bars["high"].max()), float(bars["low"].min())


def _dedupe(values: list[float], tolerance_pct: float) -> list[float]:
    out: list[float] = []
    for v in sorted(values):
        if not out or v - out[-1] > out[-1] * tolerance_pct:
            out.append(v)
    return out


def key_levels(daily: pd.DataFrame, as_of_date: date, swing_lookback: int = 60, swing_n: int = 2,
               tolerance_pct: float = 0.002) -> list[float]:
    prior = _before(daily, as_of_date)
    levels: list[float] = []
    pd_hlc = prev_day_hlc(prior, as_of_date)
    if pd_hlc:
        levels += [pd_hlc[0], pd_hlc[1]]
    pw = prev_week_hl(prior, as_of_date)
    if pw:
        levels += list(pw)
    sw = swings(prior, swing_n).tail(swing_lookback)
    levels += sw["swing_high"].dropna().tolist() + sw["swing_low"].dropna().tolist()
    return _dedupe([float(v) for v in levels if np.isfinite(v)], tolerance_pct)


def nearest_level_above(price: float, levels: list[float]) -> float | None:
    above = [l for l in levels if l > price]
    return min(above) if above else None


def nearest_level_below(price: float, levels: list[float]) -> float | None:
    below = [l for l in levels if l < price]
    return max(below) if below else None
