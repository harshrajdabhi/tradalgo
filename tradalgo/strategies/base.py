from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Literal, Protocol

import pandas as pd

Direction = Literal["long", "short"]


class Regime(str, Enum):
    TREND_UP = "trend_up"
    TREND_DOWN = "trend_down"
    RANGE = "range"
    HIGH_VOL = "high_vol"


@dataclass(frozen=True)
class Signal:
    """A detected setup on the last CLOSED 5m candle. `ts` is that candle's start time (IST)."""

    symbol: str
    strategy: str
    direction: Direction
    ts: datetime
    entry: float
    stop_loss: float
    regime: Regime
    market_regime: Regime
    counter_trend: bool
    reason: str
    features: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.ts.tzinfo is None:
            raise ValueError("Signal.ts must be timezone-aware")
        wrong_side = self.stop_loss >= self.entry if self.direction == "long" else self.stop_loss <= self.entry
        if wrong_side:
            raise ValueError(f"stop_loss {self.stop_loss} on wrong side of entry {self.entry} for {self.direction}")

    @property
    def risk_per_share(self) -> float:
        return abs(self.entry - self.stop_loss)

    def target(self, r: float) -> float:
        sign = 1 if self.direction == "long" else -1
        return self.entry + sign * r * self.risk_per_share


@dataclass(frozen=True)
class MarketContext:
    """Everything a detector may look at. Frames contain only closed candles up to `now`."""

    symbol: str
    now: datetime
    candles_5m: pd.DataFrame      # today's session + prior days, IST index
    candles_15m: pd.DataFrame
    daily: pd.DataFrame           # completed daily candles BEFORE today
    index_15m: pd.DataFrame       # NIFTY50 15m candles
    regime: Regime
    market_regime: Regime


class Detector(Protocol):
    name: str
    counter_trend: bool

    def __call__(self, ctx: MarketContext) -> Signal | None: ...
