from dataclasses import dataclass
from datetime import datetime
from typing import Literal

EventKind = Literal["stop_hit", "partial_exit", "trail_update", "runner_exit", "hard_exit"]


@dataclass(frozen=True)
class PositionEvent:
    """A management instruction for an open trade; becomes a Telegram alert live, a fill in backtest."""

    kind: EventKind
    trade_id: int
    symbol: str
    strategy: str
    ts: datetime
    price: float          # price at which the event triggered / should be executed
    qty: int              # quantity to exit (0 for trail_update)
    new_stop: float | None
    r_multiple: float     # R of this exit leg (0 for trail_update)
