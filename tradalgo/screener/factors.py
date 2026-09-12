"""The spec's 7 ranking factors, from completed daily candles strictly before trade_date.

Factors score quality in the bias direction (strong weakness scores as high as strong strength for a short).
momentum/volatility/volume/structure use magnitudes; relative_strength ranks RS signed by bias; news is
bias-adjusted (short = 100 - sentiment) and passed through. Raw components are cross-sectionally
percentile-ranked (0..100) and averaged. Structure formula: close beyond the prior 20-day high (long) / low
(short) = breakout = 100; otherwise tightness (100 - own Bollinger-width percentile) x extremity (|2*pos-1|,
pos = close position in the 20-day range, so 1 near highs/lows); NR7 adds 10.
Room: the first key level on the bias side within trigger_zone_atr x ATR14 of the close is the trigger; room_atr
is measured from the trigger (or the close if none) to the next level beyond it.
"""
from datetime import date

import numpy as np
import pandas as pd

from tradalgo import indicators as ind
from tradalgo.data.universe import Constituent

FACTOR_KEYS = (
    "momentum_trend", "relative_strength", "volatility", "relative_volume",
    "structure", "level_proximity", "news_sentiment",
)
MIN_HISTORY = 60
ROOM_CAP_ATR = 5.0


def _ret(close: pd.Series, n: int) -> float:
    return float(close.iloc[-1] / close.iloc[-n - 1] - 1) if len(close) > n else float("nan")


def _xrank(values: pd.Series) -> pd.Series:
    return (values.astype(float).rank(pct=True) * 100).fillna(50.0)


def _level_name(level: float, pdh_l, pw_hl, tol: float) -> str:
    named = {}
    if pdh_l:
        named.update(PDH=pdh_l[0], PDL=pdh_l[1])
    if pw_hl:
        named.update(PWH=pw_hl[0], PWL=pw_hl[1])
    for name, value in named.items():
        if abs(value - level) <= level * tol:
            return name
    return "swing level"


def _raw(d: pd.DataFrame, trade_date: date, index_ret20: float, trigger_zone_atr: float) -> dict:
    close = d["close"]
    last = float(close.iloc[-1])
    ema20 = ind.ema(close, 20)
    atr14 = float(ind.atr(d, 14).iloc[-1])
    ret20 = _ret(close, 20)
    rs_nifty = ret20 - index_ret20
    direction = "long" if ret20 + rs_nifty >= 0 else "short"

    hi20 = d["high"].iloc[-21:-1].max()
    lo20 = d["low"].iloc[-21:-1].min()
    breakout = (direction == "long" and last > hi20) or (direction == "short" and last < lo20)
    rng_hi, rng_lo = d["high"].iloc[-20:].max(), d["low"].iloc[-20:].min()
    pos = (last - rng_lo) / (rng_hi - rng_lo) if rng_hi > rng_lo else 0.5
    tightness = 100 - np.nan_to_num(ind.bb_width_percentile(d).iloc[-1], nan=50.0)
    structure = 100.0 if breakout else tightness * abs(2 * pos - 1) + (10.0 if ind.nr7(d).iloc[-1] else 0.0)

    tol = 0.002
    levels = ind.key_levels(d, trade_date, tolerance_pct=tol)
    side = sorted((l for l in levels if l > last)) if direction == "long" else \
        sorted((l for l in levels if l < last), reverse=True)
    trigger = None
    # A level hugging the close on the bias side is the entry trigger (e.g. PDH breakout), not the blocker.
    if side and atr14 > 0 and abs(side[0] - last) <= trigger_zone_atr * atr14:
        trigger = side.pop(0)
    level = side[0] if side else None
    ref = trigger if trigger is not None else last
    room_atr = abs(level - ref) / atr14 if level is not None and atr14 > 0 else float("nan")
    pdh_l, pw_hl = ind.prev_day_hlc(d, trade_date), ind.prev_week_hl(d, trade_date)

    volume = d["volume"]
    vol20 = volume.iloc[-20:].mean()
    return {
        "direction": direction, "close": last, "ret20": ret20, "rs_nifty": rs_nifty,
        "ema_slope": float(ema20.iloc[-1] / ema20.iloc[-6] - 1),
        "adx14": float(ind.adx(d, 14)["adx"].iloc[-1]),
        "atr14": atr14, "atr_pct": atr14 / last,
        "atr_pct_pctile": float(ind.atr_pct_percentile(d).iloc[-1]),
        "rv_pctile": float(ind.realized_vol_percentile(d).iloc[-1]),
        "rvol": ind.daily_relative_volume(d, 20),
        "vol_expansion": float(volume.iloc[-5:].mean() / vol20) if vol20 > 0 else float("nan"),
        "structure_raw": structure,
        "nearest_level": level,
        "level_name": _level_name(level, pdh_l, pw_hl, tol) if level is not None else None,
        "trigger_level": trigger,
        "trigger_name": _level_name(trigger, pdh_l, pw_hl, tol) if trigger is not None else None,
        "room_atr": room_atr,
    }


def compute_factors(daily_by_symbol: dict[str, pd.DataFrame], index_daily: pd.DataFrame,
                    universe: list[Constituent], trade_date: date,
                    news_scores: dict[str, float] | None = None, trigger_zone_atr: float = 0.25) -> pd.DataFrame:
    """One row per symbol with enough history: the 7 factor scores (0..100) plus raw fields used for reasons."""
    news_scores = news_scores or {}
    index_prior = index_daily[index_daily.index.date < trade_date]
    index_ret20 = _ret(index_prior["close"], 20)
    industry = {c.symbol: c.industry for c in universe}

    raw = {}
    for c in universe:
        df = daily_by_symbol.get(c.symbol)
        if df is None:
            continue
        d = df[df.index.date < trade_date]
        if len(d) >= MIN_HISTORY:
            raw[c.symbol] = _raw(d, trade_date, index_ret20, trigger_zone_atr)
    out = pd.DataFrame.from_dict(raw, orient="index")
    if out.empty:
        return pd.DataFrame(columns=list(FACTOR_KEYS))

    sector_of = pd.Series({s: industry[s] for s in out.index})
    sums = out["ret20"].groupby(sector_of).transform("sum")
    counts = out["ret20"].groupby(sector_of).transform("count")
    peer_mean = (sums - out["ret20"]) / (counts - 1)
    out["rs_sector"] = (out["ret20"] - peer_mean).where(counts > 1, 0.0)

    out["momentum_trend"] = (_xrank(out["ret20"].abs()) + _xrank(out["ema_slope"].abs()) + _xrank(out["adx14"])) / 3
    sign = out["direction"].map({"long": 1.0, "short": -1.0})
    out["relative_strength"] = (_xrank(sign * out["rs_nifty"]) + _xrank(sign * out["rs_sector"])) / 2
    out["volatility"] = (_xrank(out["atr_pct"]) + _xrank(out["atr_pct_pctile"]) + _xrank(out["rv_pctile"])) / 3
    out["relative_volume"] = (_xrank(out["rvol"]) + _xrank(out["vol_expansion"])) / 2
    out["structure"] = _xrank(out["structure_raw"])
    out["level_proximity"] = _xrank(out["room_atr"].astype(float).fillna(ROOM_CAP_ATR).clip(upper=ROOM_CAP_ATR))
    news = pd.Series({s: float(news_scores.get(s, 50.0)) for s in out.index})
    out["news_sentiment"] = news.where(out["direction"] == "long", 100.0 - news)
    return out
