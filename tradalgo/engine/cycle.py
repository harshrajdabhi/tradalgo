"""The one decision cycle shared by the live session and the backtest replay. No I/O: everything goes to the sink."""
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from typing import Callable, Protocol

import pandas as pd

from tradalgo import regime as regime_mod
from tradalgo.clock import IST, MarketCalendar, to_ist
from tradalgo.config import Settings
from tradalgo.engine.events import PositionEvent
from tradalgo.engine.positions import PositionManager
from tradalgo.indicators.levels import key_levels, opening_range
from tradalgo.risk.limits import DailyRiskState, kill_switch_active, register_entry, register_exit
from tradalgo.risk.plan import Rejection, TradePlan
from tradalgo.risk.validator import validate as validate_signal
from tradalgo.strategies import registry
from tradalgo.strategies.base import MarketContext, Regime, Signal

BAR = pd.Timedelta(minutes=5)
BAR_15 = pd.Timedelta(minutes=15)
HISTORY_SESSIONS = 5
REGIME_HISTORY_SESSIONS = 20
AGG = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}


@dataclass(frozen=True)
class SymbolFrames:
    candles_5m: pd.DataFrame   # may hold any amount of history; sliced by closed_session_frames
    daily: pd.DataFrame


def closed_session_frames(candles_5m_all: pd.DataFrame, now: datetime,
                          history_sessions: int = HISTORY_SESSIONS) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(5m, 15m): the last `history_sessions` completed sessions plus today's CLOSED bars.

    Detector indicators depend on how much history the frame starts with, so live and backtest must both
    build frames here.
    """
    now_ts = pd.Timestamp(to_ist(now))
    closed = candles_5m_all[candles_5m_all.index + BAR <= now_ts]
    if closed.empty:
        return closed, closed.copy()
    dates = closed.index.date
    prior = sorted({d for d in set(dates) if d < now_ts.date()})[-history_sessions:]
    c5 = closed[pd.Index(dates).isin(set(prior) | {now_ts.date()})]
    c15 = c5.resample("15min").agg(AGG).dropna(subset=["open"])
    return c5, c15[c15.index + BAR_15 <= now_ts]


def daily_before(daily_all: pd.DataFrame, day: date) -> pd.DataFrame:
    return daily_all[daily_all.index.date < day]


def _context(symbol, now, c5, c15, daily, index_15m, regime, market_regime) -> MarketContext:
    return MarketContext(symbol=symbol, now=now, candles_5m=c5, candles_15m=c15, daily=daily,
                         index_15m=index_15m, regime=regime, market_regime=market_regime)


def build_context(symbol: str, now: datetime, candles_5m_all: pd.DataFrame, daily_all: pd.DataFrame,
                  index_5m_all: pd.DataFrame, regime: Regime, market_regime: Regime,
                  history_sessions: int = HISTORY_SESSIONS) -> MarketContext:
    now = to_ist(now)
    c5, c15 = closed_session_frames(candles_5m_all, now, history_sessions)
    _, i15 = closed_session_frames(index_5m_all, now, history_sessions)
    return _context(symbol, now, c5, c15, daily_before(daily_all, now.date()), i15, regime, market_regime)


def session_levels(daily: pd.DataFrame, candles_5m: pd.DataFrame, now: datetime,
                   session_open=None, or_minutes: int = 15) -> list[float]:
    """Key daily levels plus today's opening-range high/low once the opening range has completed."""
    day = to_ist(now).date()
    levels = key_levels(daily, day)
    open_t = session_open or datetime.strptime("09:15", "%H:%M").time()
    if to_ist(now) >= datetime.combine(day, open_t, tzinfo=IST) + timedelta(minutes=or_minutes):
        rng = opening_range(candles_5m, day, or_minutes, open_t)
        if rng:
            levels = sorted({*levels, *rng})
    return levels


class CycleSink(Protocol):
    def record_signal(self, signal: Signal) -> int: ...
    def record_decision(self, signal_id: int, decision: TradePlan | Rejection) -> None: ...
    def accept(self, plan: TradePlan, signal_id: int) -> int | None:
        """trade_id, or None when the entry did not happen (backtest: next open outside the limit band)."""
    def emit_event(self, event: PositionEvent, taken: bool) -> None: ...
    def is_taken(self, trade_id: int) -> bool: ...


@dataclass
class CycleDeps:
    settings: Settings
    calendar: MarketCalendar
    classify: Callable = regime_mod.classify
    detect_all: Callable = registry.detect_all
    validate: Callable = validate_signal
    levels: Callable = session_levels        # (daily, candles_5m, now) -> list[float]
    leverage: Callable[[str], float | None] = lambda symbol: None
    history_sessions: int = HISTORY_SESSIONS
    regime_history_sessions: int = REGIME_HISTORY_SESSIONS


@dataclass
class SessionState:
    trade_date: date
    capital: float
    risk: DailyRiskState
    # one PositionManager per symbol: on_price applies a bar to every open trade it holds
    position_manager: dict[str, PositionManager] = field(default_factory=dict)
    taken_trade_ids: set[int] = field(default_factory=set)
    seen_signals: set[tuple[str, str, str]] = field(default_factory=set)
    trades: dict[int, dict] = field(default_factory=dict)

    @classmethod
    def new(cls, trade_date: date, capital: float) -> "SessionState":
        return cls(trade_date, capital, DailyRiskState(trade_date))

    def to_dict(self) -> dict:
        r = self.risk
        return {
            "trade_date": self.trade_date.isoformat(), "capital": self.capital,
            "risk": {"trade_date": r.trade_date.isoformat(), "trades_taken": r.trades_taken,
                     "realized_r": r.realized_r, "open_trade_symbols": list(r.open_trade_symbols),
                     "taken": [list(t) for t in r.taken]},
            "position_manager": {s: pm.to_dict() for s, pm in self.position_manager.items()},
            "taken_trade_ids": sorted(self.taken_trade_ids),
            "seen_signals": sorted(list(k) for k in self.seen_signals),
            "trades": {str(k): v for k, v in self.trades.items()},
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SessionState":
        r = d["risk"]
        risk = DailyRiskState(date.fromisoformat(r["trade_date"]), r["trades_taken"], r["realized_r"],
                              list(r["open_trade_symbols"]), [tuple(t) for t in r["taken"]])
        return cls(
            trade_date=date.fromisoformat(d["trade_date"]), capital=d["capital"], risk=risk,
            position_manager={s: PositionManager.from_dict(pm) for s, pm in d["position_manager"].items()},
            taken_trade_ids=set(d["taken_trade_ids"]),
            seen_signals={tuple(k) for k in d["seen_signals"]},
            trades={int(k): v for k, v in d["trades"].items()},
        )


def _cost_r(settings: Settings, meta: dict) -> float:
    return settings.capital.fixed_cost_rupees / (meta["qty"] * meta["risk_per_share"])


def register_taken(state: SessionState, trade_id: int, settings: Settings | None = None) -> None:
    """Count a trade toward the daily cap/loss limit. Idempotent. Live: call when the user taps Taken."""
    if trade_id in state.taken_trade_ids:
        return
    meta = state.trades[trade_id]
    state.taken_trade_ids.add(trade_id)
    state.risk = register_entry(state.risk, SimpleNamespace(symbol=meta["symbol"], strategy=meta["strategy"]))
    if meta["closed"] and settings is not None:
        state.risk = register_exit(state.risk, meta["symbol"], meta["gross_r"] - _cost_r(settings, meta))


def _manage_open_trades(state: SessionState, views: dict, deps: CycleDeps, sink: CycleSink) -> None:
    for symbol, pm in state.position_manager.items():
        if not pm.open_trades() or symbol not in views:
            continue
        c5 = views[symbol][0]
        if c5.empty or c5.index[-1].date() != state.trade_date:
            continue
        start, bar = c5.index[-1], c5.iloc[-1]
        events = pm.on_price((start + BAR).to_pydatetime(), float(bar["high"]), float(bar["low"]),
                             float(bar["close"]), True, open=float(bar["open"]))
        route_events(state, pm, events, deps.settings, sink)


def route_events(state: SessionState, pm: PositionManager, events: list[PositionEvent], settings: Settings,
                 sink: CycleSink) -> None:
    """Book exit legs into state, emit each event with its taken flag, and count taken exits in risk state.

    Shared by closed-bar management here and live tick management.
    """
    still_open = {t.trade_id for t in pm.open_trades()}
    for ev in events:
        meta = state.trades[ev.trade_id]
        meta["gross_r"] += float(ev.r_multiple) * ev.qty / meta["qty"]
        taken = sink.is_taken(ev.trade_id)
        if taken:
            register_taken(state, ev.trade_id)
        sink.emit_event(ev, taken)
    for trade_id in sorted({ev.trade_id for ev in events} - still_open):
        meta = state.trades[trade_id]
        meta["closed"] = True
        if trade_id in state.taken_trade_ids:
            state.risk = register_exit(state.risk, meta["symbol"], meta["gross_r"] - _cost_r(settings, meta))


def open_position(state: SessionState, plan: TradePlan, trade_id: int, settings: Settings) -> None:
    """Start managing an accepted trade. Live crash recovery reuses this to re-open DB trades."""
    s, sig = settings, plan.signal
    pm = state.position_manager.get(sig.symbol)
    if pm is None:
        pm = state.position_manager[sig.symbol] = PositionManager(
            partial_fraction=s.position_management.partial_exit_fraction, trail_bars=s.risk.trail_bars,
            hard_exit=s.market.hard_exit)
    pm.open(trade_id, plan)
    state.trades[trade_id] = {"symbol": sig.symbol, "strategy": sig.strategy, "qty": plan.qty,
                              "risk_per_share": sig.risk_per_share, "gross_r": 0.0, "closed": False}
    state.seen_signals.add((sig.symbol, sig.strategy, sig.ts.isoformat()))


def _enter(state: SessionState, plan: TradePlan, signal_id: int, deps: CycleDeps, sink: CycleSink) -> None:
    trade_id = sink.accept(plan, signal_id)
    if trade_id is None:
        return
    open_position(state, plan, trade_id, deps.settings)
    if sink.is_taken(trade_id):
        register_taken(state, trade_id)


def run_cycle(state: SessionState, now: datetime, frames_by_symbol: dict[str, SymbolFrames],
              index_5m: pd.DataFrame, deps: CycleDeps, sink: CycleSink, *, check_kill_switch: bool) -> None:
    now = to_ist(now)
    s = deps.settings
    views = {}
    for symbol, f in frames_by_symbol.items():
        c5, c15 = closed_session_frames(f.candles_5m, now, deps.history_sessions)
        views[symbol] = (c5, c15, daily_before(f.daily, state.trade_date))

    _manage_open_trades(state, views, deps, sink)
    if check_kill_switch and kill_switch_active(s.paths.data_dir):
        return

    # the classifier's time-of-day volatility baseline needs ~20 sessions; detectors keep exactly history_sessions
    _, i15 = closed_session_frames(index_5m, now, deps.history_sessions)
    ri5, ri15 = closed_session_frames(index_5m, now, deps.regime_history_sessions)
    market_regime = deps.classify(ri15, ri5)
    for symbol in sorted(views):
        c5, c15, daily = views[symbol]
        r5, r15 = closed_session_frames(frames_by_symbol[symbol].candles_5m, now, deps.regime_history_sessions)
        ctx = _context(symbol, now, c5, c15, daily, i15, deps.classify(r15, r5), market_regime)
        for signal in deps.detect_all(ctx, s, deps.calendar):
            key = (signal.symbol, signal.strategy, signal.ts.isoformat())
            if key in state.seen_signals:
                continue
            state.seen_signals.add(key)
            signal_id = sink.record_signal(signal)
            decision = deps.validate(
                signal, capital=state.capital, capital_cfg=s.capital,
                symbol_leverage=deps.leverage(signal.symbol), levels=deps.levels(daily, c5, now),
                limits_state=state.risk, win_prob=s.risk.win_prob, runner_avg_r=s.risk.runner_avg_r,
                min_room_r=s.risk.min_room_r, partial_fraction=s.position_management.partial_exit_fraction,
                band_fraction_r=s.risk.band_fraction_r,
            )
            sink.record_decision(signal_id, decision)
            if isinstance(decision, TradePlan):
                _enter(state, decision, signal_id, deps, sink)
