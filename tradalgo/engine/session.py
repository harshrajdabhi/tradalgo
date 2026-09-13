"""The live market-session process: the shared run_cycle every 5 minutes, ticks for open trades, EOD summary.

Never places orders; it only writes SQLite rows and queues Telegram alerts.
"""
import json
import os
import threading
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Callable

from sqlalchemy import Engine, func, insert, select

from tradalgo.clock import Clock, MarketCalendar, load_holidays, to_ist
from tradalgo.config import Settings, load_leverage_overrides
import pandas as pd

from tradalgo.data.base import INDEX_SYMBOL, normalize
from tradalgo.engine.cycle import (CycleDeps, SessionState, SymbolFrames, _cost_r, open_position, register_taken,
                                   route_events, run_cycle)
from tradalgo.notify.sender import enqueue_text_alert
from tradalgo.notify.templates import eod_summary_message
from tradalgo.notify.updates import process_updates
from tradalgo.risk.limits import kill_switch_active, register_exit
from tradalgo.risk.plan import TradePlan
from tradalgo.strategies.base import Regime, Signal
from tradalgo.storage import repo
from tradalgo.storage.schema import alerts, decisions, health_events, paper_trades, shortlist, signals, user_actions

TZ = "Asia/Kolkata"
CYCLE_START, CYCLE_END = time(9, 20), time(15, 30)


def _health(engine: Engine, component: str, level: str, message: str, now: datetime) -> None:
    with engine.begin() as conn:
        conn.execute(insert(health_events).values(ts=to_ist(now).isoformat(), component=component,
                                                  level=level, message=message))


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def state_path(state_dir: Path, trade_date: date) -> Path:
    return Path(state_dir) / f"session_state_{trade_date.isoformat()}.json"


def shortlist_symbols(engine: Engine, trade_date: date) -> list[str]:
    with engine.connect() as conn:
        return list(conn.execute(select(shortlist.c.symbol).where(
            shortlist.c.trade_date == trade_date.isoformat(), shortlist.c.demoted == 0,
        ).order_by(shortlist.c.rank)).scalars())


class LiveSession:
    def __init__(self, settings: Settings, engine: Engine, clock: Clock, provider, cache,
                 sink_factory: Callable[[Callable[[], bool]], object],
                 tick_stream_factory: Callable[[Callable], object] | None = None, state_dir: Path | None = None,
                 *, calendar: MarketCalendar | None = None, cycle_overrides: dict | None = None,
                 history_days_5m: int = 35, history_days_daily: int = 120):
        self.settings, self.engine, self.clock, self.provider, self.cache = settings, engine, clock, provider, cache
        self.sink_factory, self.tick_stream_factory = sink_factory, tick_stream_factory
        self.state_dir = Path(state_dir) if state_dir else Path(settings.paths.data_dir) / "session"
        self.calendar, self.cycle_overrides = calendar, cycle_overrides or {}
        # ~35 calendar days covers the classifier's 20 prior trading sessions
        self.history_days_5m, self.history_days_daily = history_days_5m, history_days_daily
        self._lock = threading.Lock()
        self.state: SessionState | None = None
        self.symbols: list[str] = []
        self.sink = self.stream = self.deps = None
        self._job_id: int | None = None
        self._since_action_id = 0
        self._degraded = False
        self._subscribed: set[str] = set()
        self._finished = False
        self._excursions: dict[int, tuple[float, float]] = {}

    def start(self, trade_date: date) -> bool:
        now = self.clock.now()
        s = self.settings
        calendar = self.calendar or MarketCalendar(s.market, load_holidays(s.paths.static_dir, trade_date.year))
        if not calendar.is_trading_day(trade_date):
            return False
        self._job_id = repo.start_job_run(self.engine, "session", now)
        self.symbols = shortlist_symbols(self.engine, trade_date)
        if not self.symbols:
            _health(self.engine, "session", "warning", f"no shortlist for {trade_date}; session not started", now)
            repo.finish_job_run(self.engine, self._job_id, now, error="empty shortlist")
            return False
        path = state_path(self.state_dir, trade_date)
        self.state = (SessionState.from_dict(json.loads(path.read_text())) if path.exists()
                      else SessionState.new(trade_date, s.capital.initial_capital))
        overrides = {k: min(float(v), s.capital.max_leverage) for k, v in load_leverage_overrides(s.paths.static_dir).items()}
        self.deps = CycleDeps(settings=s, calendar=calendar, leverage=overrides.get)
        for name, value in self.cycle_overrides.items():
            setattr(self.deps, name, value)
        self.sink = self.sink_factory(lambda: self._degraded)
        self._finished = False
        self._reconcile()
        self._persist()
        if self.tick_stream_factory is not None:
            self.stream = self.tick_stream_factory(self.on_tick)
            self.stream.start()
            self._subscribed = set()
            self._sync_subscriptions()
        return True

    def run_once(self, now: datetime) -> None:
        now = to_ist(now)
        with self._lock:
            try:
                self._cycle(now)
            except Exception as exc:  # one bad cycle must not end the trading day
                _health(self.engine, "session", "error", f"cycle {now.isoformat()} failed: {exc!r}", now)

    def _cycle(self, now: datetime) -> None:
        day = self.state.trade_date
        yesterday = day - timedelta(days=1)
        start_5m, start_1d = day - timedelta(days=self.history_days_5m), day - timedelta(days=self.history_days_daily)

        def five_minute(sym: str) -> pd.DataFrame:
            # the cache never refetches a day it already holds, so today's growing bars bypass it (and stay unpersisted)
            prior = self.cache.get(sym, "5m", start_5m, yesterday)
            return normalize(pd.concat([prior, self.provider.get_candles(sym, "5m", day, day)]))

        frames = {sym: SymbolFrames(five_minute(sym), self.cache.get(sym, "1d", start_1d, yesterday))
                  for sym in self.symbols}
        index_5m = five_minute(INDEX_SYMBOL)
        self._track_degraded(now)
        ids, self._since_action_id = self.sink.newly_taken_trade_ids(self._since_action_id)
        for trade_id in ids:
            if trade_id in self.state.trades:
                register_taken(self.state, trade_id, self.settings)
        run_cycle(self.state, now, frames, index_5m, self.deps, self.sink, check_kill_switch=True)
        self._after_change()

    def _after_change(self) -> None:
        self._persist()
        self._write_excursions()
        self._sync_subscriptions()

    def _restore_legs(self, st: SessionState, row, trade_id: int) -> None:
        """A partial written to the DB but lost from the state must not be emitted (or counted) twice."""
        if row["partial_exit_ts"] is None:
            return
        pm = st.position_manager[st.trades[trade_id]["symbol"]]
        if not any(t.trade_id == trade_id and t.partial_done for t in pm.trades()):
            pm.restore_partial(trade_id)
            st.trades[trade_id]["gross_r"] = row["gross_r"] or 0.0

    def _write_excursions(self) -> None:
        for pm in self.state.position_manager.values():
            for t in pm.trades():
                if self._excursions.get(t.trade_id) != (t.mfe_r, t.mae_r):
                    self.sink.record_excursions(t.trade_id, t.mfe_r, t.mae_r)
                    self._excursions[t.trade_id] = (t.mfe_r, t.mae_r)

    def _reconcile(self) -> None:
        """Adopt DB trades the saved state missed: a crash between a DB write and the state save."""
        like = f"{self.state.trade_date.isoformat()}%"
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(paper_trades.c.id.label("trade_id"), paper_trades.c.qty, paper_trades.c.exit_ts,
                       paper_trades.c.gross_r, paper_trades.c.partial_exit_ts, signals.c.ts, signals.c.symbol, signals.c.strategy,
                       signals.c.direction, signals.c.regime, signals.c.market_regime, signals.c.entry,
                       signals.c.stop_loss, signals.c.target_2r, signals.c.target_3r, decisions.c.leverage_used,
                       decisions.c.risk_rupees, decisions.c.est_cost, decisions.c.expected_value_r,
                       decisions.c.room_to_target_r)
                .join(signals, signals.c.id == paper_trades.c.signal_id)
                .outerjoin(decisions, decisions.c.signal_id == signals.c.id)
                .where(signals.c.mode == "live", paper_trades.c.entry_ts.like(like))
                .order_by(paper_trades.c.id)).mappings().all()
        st, s = self.state, self.settings
        for r in rows:
            trade_id = r["trade_id"]
            if trade_id not in st.trades:
                if r["exit_ts"] is None:
                    open_position(st, _plan_from_row(r), trade_id, s)
                    self._restore_legs(st, r, trade_id)
                    if self.sink.is_taken(trade_id):
                        register_taken(st, trade_id, s)
                continue
            meta = st.trades[trade_id]
            if r["exit_ts"] is None:
                self._restore_legs(st, r, trade_id)
                continue
            if not meta["closed"]:
                st.position_manager[meta["symbol"]].close(trade_id)
                meta["gross_r"], meta["closed"] = r["gross_r"] or 0.0, True
                if trade_id in st.taken_trade_ids:
                    st.risk = register_exit(st.risk, meta["symbol"], meta["gross_r"] - _cost_r(s, meta))
                elif self.sink.is_taken(trade_id):
                    register_taken(st, trade_id, s)

    def _track_degraded(self, now: datetime) -> None:
        degraded = bool(getattr(self.provider, "degraded", False))
        if degraded != self._degraded:
            self._degraded = degraded
            if degraded:
                _health(self.engine, "data", "warning", "market data degraded: using fallback provider", now)
            else:
                _health(self.engine, "data", "info", "market data recovered: primary provider", now)

    def on_tick(self, symbol: str, ts: datetime, ltp: float) -> None:
        with self._lock:
            if self.state is None:
                return
            pm = self.state.position_manager.get(symbol)
            if pm is None or not pm.open_trades():
                return
            try:
                events = pm.on_price(to_ist(ts), ltp, ltp, ltp, False, open=ltp)
                if events:
                    route_events(self.state, pm, events, self.settings, self.sink)
                    self._after_change()
            except Exception as exc:
                _health(self.engine, "session", "error", f"tick {symbol} failed: {exc!r}", self.clock.now())

    def finish(self, now: datetime) -> None:
        self.run_once(now)
        with self._lock:
            if self._finished:
                return
            day = self.state.trade_date
            if self.settings.telegram.enabled:
                enqueue_text_alert(self.engine, "eod", f"eod:{day.isoformat()}",
                                   eod_summary_message(eod_stats(self.engine, day)), now)
            if self._job_id is not None:
                repo.finish_job_run(self.engine, self._job_id, now)
            self._finished = True
        if self.stream is not None:
            self.stream.stop()  # outside the lock: close_connection may wait on a socket thread blocked in on_tick

    def _persist(self) -> None:
        _write_atomic(state_path(self.state_dir, self.state.trade_date), json.dumps(self.state.to_dict()))

    def _sync_subscriptions(self) -> None:
        if self.stream is None:
            return
        wanted = {sym for sym, pm in self.state.position_manager.items() if pm.open_trades()}
        if wanted - self._subscribed:
            self.stream.subscribe(sorted(wanted - self._subscribed))
        if self._subscribed - wanted:
            self.stream.unsubscribe(sorted(self._subscribed - wanted))
        self._subscribed = wanted


def _plan_from_row(r) -> TradePlan:
    signal = Signal(symbol=r["symbol"], strategy=r["strategy"], direction=r["direction"],
                    ts=datetime.fromisoformat(r["ts"]), entry=r["entry"], stop_loss=r["stop_loss"],
                    regime=Regime(r["regime"]), market_regime=Regime(r["market_regime"]), counter_trend=False,
                    reason="recovered after restart", features={})
    leverage = r["leverage_used"] or 1.0
    return TradePlan(signal=signal, qty=r["qty"], leverage_used=leverage, margin_required=r["qty"] * r["entry"] / leverage,
                     risk_rupees=r["risk_rupees"] or 0.0, target_2r=r["target_2r"], target_3r=r["target_3r"],
                     est_cost=r["est_cost"] or 0.0, room_to_level_r=r["room_to_target_r"] or 0.0,
                     expected_value_r=r["expected_value_r"] or 0.0, limit_low=r["entry"], limit_high=r["entry"],
                     valid_until=datetime.fromisoformat(r["ts"]))


def eod_stats(engine: Engine, day: date) -> dict:
    like = f"{day.isoformat()}%"
    with engine.connect() as conn:
        sent = conn.execute(select(func.count()).select_from(alerts).where(
            alerts.c.created_at.like(like), alerts.c.alert_type.in_(("entry", "event")),
            alerts.c.status.in_(("sent", "edited", "expired")))).scalar()
        actions = dict(conn.execute(select(user_actions.c.action, func.count()).where(
            user_actions.c.ts.like(like)).group_by(user_actions.c.action)).all())
        closed = conn.execute(
            select(paper_trades.c.net_r, paper_trades.c.qty, signals.c.entry, signals.c.stop_loss)
            .join(signals, signals.c.id == paper_trades.c.signal_id)
            .where(paper_trades.c.taken_by_user == 1, paper_trades.c.exit_ts.like(like))).mappings().all()
    return {"trade_date": day.isoformat(), "alerts_sent": sent, "taken": actions.get("taken", 0),
            "skipped": actions.get("skipped", 0), "closed_trades": len(closed),
            "net_r": sum(r["net_r"] or 0.0 for r in closed),
            "net_rupees": sum((r["net_r"] or 0.0) * r["qty"] * abs(r["entry"] - r["stop_loss"]) for r in closed)}


def in_window(now: datetime) -> bool:
    return CYCLE_START <= to_ist(now).replace(second=0, microsecond=0).time() <= CYCLE_END


def schedule(session: LiveSession, scheduler, on_finish: Callable[[], None] = lambda: None) -> None:
    from apscheduler.triggers.cron import CronTrigger

    def cycle_job():
        now = session.clock.now()
        if in_window(now):
            session.run_once(now)

    def finish_job():
        session.finish(session.clock.now())
        on_finish()

    scheduler.add_job(cycle_job, CronTrigger(day_of_week="mon-fri", hour="9-15", minute="*/5", second=10,
                                             timezone=TZ), id="session_cycle", max_instances=1, coalesce=True)
    scheduler.add_job(finish_job, CronTrigger(day_of_week="mon-fri", hour=15, minute=31, timezone=TZ),
                      id="session_finish", max_instances=1)


def run_session(settings: Settings, engine: Engine, clock: Clock, session: LiveSession,
                trade_date: date | None = None, scheduler_cls=None) -> bool:
    """Blocks until the 15:31 finish job. Returns False when there is no session today."""
    if scheduler_cls is None:
        from apscheduler.schedulers.blocking import BlockingScheduler
        scheduler_cls = BlockingScheduler
    now = to_ist(clock.now())
    if not session.start(trade_date or now.date()):
        return False
    if now.time() > time(15, 31):
        session.finish(now)
        return True
    scheduler = scheduler_cls(timezone=TZ)
    schedule(session, scheduler, on_finish=lambda: scheduler.shutdown(wait=False))
    scheduler.start()
    return True


def poll_telegram_updates(engine: Engine, client, clock: Clock, data_dir: Path, allowed_chat_id,
                          status_text: Callable[[], str], offset_path: Path) -> int:
    offset_path = Path(offset_path)
    offset = json.loads(offset_path.read_text())["offset"] if offset_path.exists() else 0
    new_offset = process_updates(engine, client, clock, offset, Path(data_dir), allowed_chat_id, status_text)
    if new_offset != offset:
        _write_atomic(offset_path, json.dumps({"offset": new_offset}))
    return new_offset


def status_text_for(engine: Engine, clock: Clock, state_dir: Path, data_dir: Path | None = None) -> Callable[[], str]:
    def status() -> str:
        day = to_ist(clock.now()).date()
        symbols = shortlist_symbols(engine, day)
        lines = [f"<b>Status — {day.isoformat()}</b>", f"Shortlist: {', '.join(symbols) or 'none'}"]
        path = state_path(state_dir, day)
        if path.exists():
            st = SessionState.from_dict(json.loads(path.read_text()))
            open_trades = [f"{t.symbol} {t.direction} stop {t.stop:.2f}"
                           for pm in st.position_manager.values() for t in pm.open_trades()]
            lines += [f"Open trades: {'; '.join(open_trades) or 'none'}",
                      f"Taken today: {st.risk.trades_taken}   Realized: {st.risk.realized_r:.2f} R"]
        else:
            lines.append("Session not running today")
        kill = kill_switch_active(Path(data_dir) if data_dir else Path(state_dir))
        lines.append(f"Kill switch: {'ON' if kill else 'off'}")
        return "\n".join(lines)
    return status
