from dataclasses import dataclass
from datetime import datetime

from tradalgo.strategies.base import Signal


@dataclass(frozen=True)
class TradePlan:
    """An accepted signal, sized and priced. This is what an entry alert describes."""

    signal: Signal
    qty: int
    leverage_used: float
    margin_required: float
    risk_rupees: float
    target_2r: float
    target_3r: float
    est_cost: float
    room_to_level_r: float        # distance to the nearest opposing level, in R
    expected_value_r: float       # after costs
    limit_low: float              # acceptable manual fill band
    limit_high: float
    valid_until: datetime         # alert expires after this (next candle close)


@dataclass(frozen=True)
class Rejection:
    signal: Signal
    reason: str
