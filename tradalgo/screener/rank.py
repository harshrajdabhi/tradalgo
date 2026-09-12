import math
from dataclasses import dataclass, field

import pandas as pd

from tradalgo.screener.factors import FACTOR_KEYS


@dataclass
class ScoredSymbol:
    symbol: str
    direction: str
    composite_score: float
    factor_scores: dict[str, float]
    reasons: list[str] = field(default_factory=list)
    rejected: str | None = None


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _is_num(v) -> bool:
    return v is not None and not (isinstance(v, float) and math.isnan(v))


def _reasons(row: pd.Series) -> list[str]:
    reasons = [f"{row['direction']} bias"]
    if _is_num(row.get("rs_nifty")):
        reasons.append(f"RS {row['rs_nifty'] * 100:+.1f}% vs NIFTY")
    if _is_num(row.get("rs_sector")):
        reasons.append(f"{row['rs_sector'] * 100:+.1f}% vs sector")
    if _is_num(row.get("atr_pct_pctile")):
        reasons.append(f"ATR% {_ordinal(round(row['atr_pct_pctile']))} pct")
    if _is_num(row.get("rvol")):
        reasons.append(f"RVOL {row['rvol']:.1f}x")
    trigger = row.get("trigger_name")
    beyond = f" beyond {trigger} trigger" if isinstance(trigger, str) else ""
    if _is_num(row.get("room_atr")):
        reasons.append(f"{row['room_atr']:.1f} ATR room to {row['level_name']}{beyond}")
    elif beyond:
        reasons.append(f"trigger at {trigger}, no key level beyond")
    else:
        reasons.append("no key level in the way")
    return reasons


def rank_candidates(factors: pd.DataFrame, weights: dict[str, float], liquid: set[str], blackout: set[str],
                    shortlist_size: int, stop_atr_frac: float = 0.3, min_room_r: float = 2.0) -> list[ScoredSymbol]:
    """Top `shortlist_size` valid picks by composite score, followed by every hard-rejected symbol."""
    valid, rejected = [], []
    for symbol, row in factors.iterrows():
        scores = {k: float(row[k]) for k in FACTOR_KEYS}
        item = ScoredSymbol(symbol, row["direction"], sum(weights[k] * scores[k] for k in FACTOR_KEYS),
                            scores, _reasons(row))
        room = row.get("room_atr")
        if symbol not in liquid:
            item.rejected = "fails liquidity filter (turnover/price)"
        elif symbol in blackout:
            item.rejected = "corporate event today/next trading day"
        elif _is_num(room) and room < min_room_r * stop_atr_frac:
            trigger = row.get("trigger_name")
            origin = f"{trigger} trigger" if isinstance(trigger, str) else "close"
            item.rejected = (f"2R blocked: {row['level_name']} only {room:.2f} ATR beyond {origin}, "
                             f"needs {min_room_r * stop_atr_frac:.2f} ATR ({min_room_r:g}R x {stop_atr_frac:g} ATR stop)")
        (rejected if item.rejected else valid).append(item)
    valid.sort(key=lambda s: s.composite_score, reverse=True)
    rejected.sort(key=lambda s: s.composite_score, reverse=True)
    return valid[:shortlist_size] + rejected
