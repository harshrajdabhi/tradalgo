"""CycleSink for the live session: everything goes to SQLite; Telegram alerts are only queued, never sent here.

Stateless over the DB (trade -> signal -> entry alert -> user action) so a restarted session sees the same truth.
"""
import json
from dataclasses import asdict
from datetime import datetime
from typing import Callable

from sqlalchemy import Engine, insert, select, update

from tradalgo.clock import Clock, to_ist
from tradalgo.config import CostsConfig
from tradalgo.engine.events import PositionEvent
from tradalgo.notify.sender import enqueue_entry_alert, enqueue_event_alert
from tradalgo.risk.costs import intraday_charges, split_sides
from tradalgo.risk.plan import TradePlan
from tradalgo.storage.schema import alerts, decisions, paper_trades, signals, user_actions


class LiveSink:
    def __init__(self, engine: Engine, clock: Clock, degraded_fn: Callable[[], bool], alerts_enabled: bool,
                 costs: CostsConfig | None = None):
        self.engine, self.clock, self.degraded_fn = engine, clock, degraded_fn
        self.alerts_enabled, self.costs = alerts_enabled, costs or CostsConfig()
        self._pending: list[tuple[PositionEvent, bool]] = []

    def record_signal(self, signal) -> int:
        ts = to_ist(signal.ts).isoformat()
        with self.engine.begin() as conn:
            # a restart can re-detect a signal whose row was written before the state save
            existing = conn.execute(select(signals.c.id).where(
                signals.c.mode == "live", signals.c.symbol == signal.symbol,
                signals.c.strategy == signal.strategy, signals.c.ts == ts)).scalar()
            if existing is not None:
                return existing
            return conn.execute(insert(signals).values(
                ts=to_ist(signal.ts).isoformat(), symbol=signal.symbol, strategy=signal.strategy,
                direction=signal.direction, regime=signal.regime.value, market_regime=signal.market_regime.value,
                entry=signal.entry, stop_loss=signal.stop_loss, target_2r=signal.target(2),
                target_3r=signal.target(3), features_json=json.dumps(signal.features, default=str, sort_keys=True),
                mode="live",
            )).inserted_primary_key[0]

    def record_decision(self, signal_id: int, decision) -> None:
        if isinstance(decision, TradePlan):
            values = dict(accepted=1, qty=decision.qty, leverage_used=decision.leverage_used,
                          risk_rupees=decision.risk_rupees, est_cost=decision.est_cost,
                          expected_value_r=decision.expected_value_r, room_to_target_r=decision.room_to_level_r)
        else:
            values = dict(accepted=0, rejection_reason=decision.reason)
        with self.engine.begin() as conn:
            if conn.execute(select(decisions.c.id).where(decisions.c.signal_id == signal_id)).first() is None:
                conn.execute(insert(decisions).values(signal_id=signal_id, **values))

    def accept(self, plan: TradePlan, signal_id: int) -> int:
        with self.engine.begin() as conn:
            existing = conn.execute(select(paper_trades.c.id).where(paper_trades.c.signal_id == signal_id)).scalar()
            if existing is not None:
                return existing
            trade_id = conn.execute(insert(paper_trades).values(
                signal_id=signal_id, taken_by_user=0, entry_ts=to_ist(plan.signal.ts).isoformat(),
                entry_price=plan.signal.entry, qty=plan.qty,
            )).inserted_primary_key[0]
        if self.alerts_enabled:
            enqueue_entry_alert(self.engine, plan, signal_id, self.degraded_fn(), self.clock.now())
        return trade_id

    def emit_event(self, event: PositionEvent, taken: bool) -> None:
        # save-then-alert: nothing leaves memory until the session has persisted the state these events produced
        self._pending.append((event, taken))

    def pending_events(self) -> list[dict]:
        return [{"event": {**asdict(ev), "ts": to_ist(ev.ts).isoformat()}, "taken": taken}
                for ev, taken in self._pending]

    def restore_pending(self, items: list[dict]) -> None:
        self._pending = [(PositionEvent(**{**i["event"], "ts": datetime.fromisoformat(i["event"]["ts"])}), i["taken"])
                         for i in items]

    def flush_event_alerts(self) -> int:
        """Apply buffered exit legs and queue management alerts. Safe to repeat: legs and alerts are idempotent."""
        flushed = 0
        while self._pending:
            event, taken = self._pending[0]
            if event.kind != "trail_update":
                self._record_exit_leg(event)
            if taken and self.alerts_enabled:
                enqueue_event_alert(self.engine, event, self.clock.now())
            self._pending.pop(0)
            flushed += 1
        return flushed

    def _record_exit_leg(self, event: PositionEvent) -> None:
        with self.engine.begin() as conn:
            t = conn.execute(
                select(paper_trades.c.qty, paper_trades.c.gross_r, paper_trades.c.partial_exit_ts,
                       paper_trades.c.exit_ts, paper_trades.c.partial_exit_price, signals.c.entry,
                       signals.c.stop_loss, signals.c.direction)
                .join(signals, signals.c.id == paper_trades.c.signal_id)
                .where(paper_trades.c.id == event.trade_id)
            ).mappings().one()
            ts = to_ist(event.ts).isoformat()
            closes = event.kind != "partial_exit" or event.qty >= t["qty"]
            already = t["exit_ts"] is not None if closes else t["partial_exit_ts"] is not None
            if already:
                return  # a restart can replay a leg whose DB row was written before the state save
            gross = (t["gross_r"] or 0.0) + event.r_multiple * event.qty / t["qty"]
            values = {"gross_r": gross}
            if event.kind == "partial_exit":
                values.update(partial_exit_ts=ts, partial_exit_price=event.price)
            if closes:
                risk_rupees = t["qty"] * abs(t["entry"] - t["stop_loss"])
                values.update(exit_ts=ts, exit_price=event.price, exit_reason=event.kind,
                              net_r=gross - self._charges(t, event) / risk_rupees)
            conn.execute(update(paper_trades).where(paper_trades.c.id == event.trade_id).values(**values))

    def _charges(self, t, event: PositionEvent) -> float:
        partial_qty = t["qty"] - event.qty if t["partial_exit_price"] is not None and event.kind != "partial_exit" else 0
        exits = [partial_qty * t["partial_exit_price"], event.qty * event.price] if partial_qty \
            else [t["qty"] * event.price]
        return intraday_charges(*split_sides(t["direction"], t["qty"] * t["entry"], exits), self.costs)

    def record_excursions(self, trade_id: int, mfe_r: float, mae_r: float) -> None:
        with self.engine.begin() as conn:
            conn.execute(update(paper_trades).where(paper_trades.c.id == trade_id).values(mfe_r=mfe_r, mae_r=mae_r))

    def _taken_query(self):
        return (select(user_actions.c.id, user_actions.c.action, user_actions.c.price,
                       paper_trades.c.id.label("trade_id"), paper_trades.c.qty, signals.c.entry, signals.c.direction)
                .join(alerts, alerts.c.id == user_actions.c.alert_id)
                .join(paper_trades, paper_trades.c.signal_id == alerts.c.signal_id)
                .join(signals, signals.c.id == paper_trades.c.signal_id)
                .where(alerts.c.alert_type == "entry"))

    @staticmethod
    def _mark_taken(conn, row) -> None:
        slippage = None
        # the Taken button carries no fill price: notify.updates stores the plan entry, which is not slippage
        if row["price"] is not None and row["price"] != row["entry"]:
            sign = 1 if row["direction"] == "long" else -1
            slippage = sign * (row["price"] - row["entry"]) * row["qty"]  # positive = paid worse than plan
        conn.execute(update(paper_trades).where(paper_trades.c.id == row["trade_id"]).values(
            taken_by_user=1, slippage_rupees=slippage))

    def is_taken(self, trade_id: int) -> bool:
        with self.engine.begin() as conn:
            row = conn.execute(self._taken_query().where(
                paper_trades.c.id == trade_id, user_actions.c.action == "taken").limit(1)).mappings().first()
            if row is not None:
                self._mark_taken(conn, row)
        return row is not None

    def newly_actioned_trade_ids(self, since_id: int) -> tuple[list[int], list[int], int]:
        """(taken trade ids, skipped trade ids, new cursor): skipped releases its provisional risk slot."""
        with self.engine.begin() as conn:
            found = conn.execute(self._taken_query().where(user_actions.c.id > since_id)
                                 .order_by(user_actions.c.id)).mappings().all()
            taken = [r for r in found if r["action"] == "taken"]
            for r in taken:
                self._mark_taken(conn, r)
        return ([r["trade_id"] for r in taken], [r["trade_id"] for r in found if r["action"] == "skipped"],
                max((r["id"] for r in found), default=since_id))
