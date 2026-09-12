import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, time

from tradalgo.clock import IST
from tradalgo.engine.events import PositionEvent
from tradalgo.risk.plan import TradePlan


@dataclass
class ManagedTrade:
    trade_id: int
    symbol: str
    strategy: str
    direction: str
    entry: float          # original signal entry: defines R and breakeven
    initial_stop: float
    target_2r: float
    target_3r: float
    qty: int
    filled_price: float
    stop: float
    remaining: int
    partial_done: bool = False
    closed: bool = False
    last_ts: str | None = None
    last_closed: bool = False
    closed_highs: list[float] = field(default_factory=list)
    closed_lows: list[float] = field(default_factory=list)

    @property
    def long(self) -> bool:
        return self.direction == "long"

    @property
    def risk_per_share(self) -> float:
        return abs(self.entry - self.initial_stop)

    def r_of(self, price: float) -> float:
        sign = 1 if self.long else -1
        return sign * (price - self.entry) / self.risk_per_share


class PositionManager:
    """Pure in-memory exit state machine shared by live session and backtest.

    Updates for a trade are ordered by (ts, bar_closed); anything not strictly newer is ignored, so
    replays are idempotent. When mixing ticks and bars, pass bars with a ts no older than the ticks
    already processed (e.g. the bar's close time).
    """

    def __init__(self, partial_fraction: float = 0.6, trail_bars: int = 3, hard_exit: time = time(15, 0)):
        self.partial_fraction = partial_fraction
        self.trail_bars = trail_bars
        self.hard_exit = hard_exit
        self._trades: dict[int, ManagedTrade] = {}

    def open(self, trade_id: int, plan: TradePlan, filled_price: float | None = None) -> None:
        s = plan.signal
        self._trades[trade_id] = ManagedTrade(
            trade_id=trade_id, symbol=s.symbol, strategy=s.strategy, direction=s.direction,
            entry=s.entry, initial_stop=s.stop_loss, target_2r=plan.target_2r, target_3r=plan.target_3r,
            qty=plan.qty, filled_price=s.entry if filled_price is None else filled_price,
            stop=s.stop_loss, remaining=plan.qty,
        )

    def open_trades(self) -> list[ManagedTrade]:
        return [t for t in self._trades.values() if not t.closed]

    def on_price(self, ts: datetime, high: float, low: float, close: float, bar_closed: bool) -> list[PositionEvent]:
        events: list[PositionEvent] = []
        for t in self.open_trades():
            if t.last_ts is not None and (ts, bar_closed) <= (datetime.fromisoformat(t.last_ts), t.last_closed):
                continue
            t.last_ts, t.last_closed = ts.isoformat(), bar_closed
            events += self._update(t, ts, high, low, close, bar_closed)
        return events

    def _event(self, t: ManagedTrade, kind, ts, price, qty, new_stop=None) -> PositionEvent:
        r = 0.0 if kind == "trail_update" else t.r_of(price)
        return PositionEvent(kind, t.trade_id, t.symbol, t.strategy, ts, price, qty, new_stop, r)

    def _exit(self, t: ManagedTrade, kind, ts, price) -> PositionEvent:
        ev = self._event(t, kind, ts, price, t.remaining)
        t.remaining, t.closed = 0, True
        return ev

    def _touches(self, t: ManagedTrade, level: float, high: float, low: float, favorable: bool) -> bool:
        up = t.long == favorable
        return high >= level if up else low <= level

    def _update(self, t: ManagedTrade, ts, high, low, close, bar_closed) -> list[PositionEvent]:
        # Stop is checked first: a bar touching both stop and target counts as stop-first (conservative).
        if self._touches(t, t.stop, high, low, favorable=False):
            return [self._exit(t, "stop_hit", ts, t.stop)]

        events = []
        if not t.partial_done and self._touches(t, t.target_2r, high, low, favorable=True):
            t.partial_done = True
            if t.remaining == 1:
                return [self._exit(t, "partial_exit", ts, t.target_2r)]
            qty = max(1, math.floor(t.qty * self.partial_fraction))
            events.append(self._event(t, "partial_exit", ts, t.target_2r, qty))
            t.remaining -= qty
            if self._tighten(t, t.entry):
                events.append(self._event(t, "trail_update", ts, t.target_2r, 0, t.stop))

        if t.partial_done and self._touches(t, t.target_3r, high, low, favorable=True):
            return events + [self._exit(t, "runner_exit", ts, t.target_3r)]

        if bar_closed:
            t.closed_highs = (t.closed_highs + [high])[-self.trail_bars:]
            t.closed_lows = (t.closed_lows + [low])[-self.trail_bars:]
            if t.partial_done and len(t.closed_lows) == self.trail_bars:
                candidate = min(t.closed_lows) if t.long else max(t.closed_highs)
                if self._tighten(t, candidate):
                    events.append(self._event(t, "trail_update", ts, close, 0, t.stop))

        if ts.astimezone(IST).time() >= self.hard_exit:
            events.append(self._exit(t, "hard_exit", ts, close))
        return events

    def _tighten(self, t: ManagedTrade, candidate: float) -> bool:
        new = max(t.stop, candidate) if t.long else min(t.stop, candidate)
        if new == t.stop:
            return False
        assert (new > t.stop) if t.long else (new < t.stop), "stop must never loosen"
        t.stop = new
        return True

    def to_dict(self) -> dict:
        return {
            "partial_fraction": self.partial_fraction,
            "trail_bars": self.trail_bars,
            "hard_exit": self.hard_exit.isoformat(),
            "trades": [asdict(t) for t in self._trades.values()],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PositionManager":
        pm = cls(d["partial_fraction"], d["trail_bars"], time.fromisoformat(d["hard_exit"]))
        for td in d["trades"]:
            t = ManagedTrade(**{**td, "closed_highs": list(td["closed_highs"]), "closed_lows": list(td["closed_lows"])})
            pm._trades[t.trade_id] = t
        return pm
