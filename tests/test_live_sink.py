from datetime import datetime

import pytest
from sqlalchemy import insert, select

from tradalgo.clock import IST, FixedClock
from tradalgo.engine.events import PositionEvent
from tradalgo.engine.live_sink import LiveSink
from tradalgo.risk.plan import Rejection
from tradalgo.storage.schema import alerts, decisions, paper_trades, signals, user_actions
from tests.backtest_fixtures import at, make_plan, make_signal
from tests.session_fixtures import make_db


@pytest.fixture
def engine(tmp_path):
    return make_db(tmp_path)


def sink(engine, degraded=False, alerts_enabled=True):
    return LiveSink(engine, FixedClock(at(9, 40)), lambda: degraded, alerts_enabled)


def rows(engine, table):
    with engine.connect() as conn:
        return conn.execute(select(table).order_by(table.c.id)).mappings().all()


def open_trade(engine, **kw):
    s = sink(engine, **kw)
    sig = make_signal(ts=at(9, 35))
    sid = s.record_signal(sig)
    plan = make_plan(sig, qty=100)
    s.record_decision(sid, plan)
    return s, s.accept(plan, sid), sid


def tap(engine, action="taken"):
    alert_id = rows(engine, alerts)[0]["id"]
    with engine.begin() as conn:
        return conn.execute(insert(user_actions).values(alert_id=alert_id, action=action, ts=at(9, 41).isoformat())
                            ).inserted_primary_key[0]


def ev(kind, trade_id, price, qty, r, hh=9, mm=50):
    return PositionEvent(kind, trade_id, "AAA", "orb", at(hh, mm), price, qty, None if qty else 100.0, r)


def test_accept_records_signal_decision_trade_and_degraded_entry_alert(engine):
    s, trade_id, sid = open_trade(engine, degraded=True)
    assert rows(engine, signals)[0]["mode"] == "live"
    assert rows(engine, decisions)[0]["accepted"] == 1
    t = rows(engine, paper_trades)[0]
    assert (t["id"], t["signal_id"], t["taken_by_user"], t["qty"], t["entry_price"]) == (trade_id, sid, 0, 100, 100.0)
    a = rows(engine, alerts)
    assert len(a) == 1 and a[0]["alert_type"] == "entry" and a[0]["signal_id"] == sid and "DEGRADED" in a[0]["text"]
    s.record_decision(sid, Rejection(make_signal(), "nope"))
    assert rows(engine, decisions)[1]["rejection_reason"] == "nope"


def test_alerts_disabled_still_tracks_trade(engine):
    _, trade_id, _ = open_trade(engine, alerts_enabled=False)
    assert trade_id and rows(engine, alerts) == []


def test_is_taken_and_newly_taken(engine):
    s, trade_id, _ = open_trade(engine)
    assert not s.is_taken(trade_id)
    assert s.newly_taken_trade_ids(0) == ([], 0)
    action_id = tap(engine)
    assert s.newly_taken_trade_ids(0) == ([trade_id], action_id)
    assert s.newly_taken_trade_ids(action_id) == ([], action_id)
    assert s.is_taken(trade_id) and rows(engine, paper_trades)[0]["taken_by_user"] == 1


def test_skipped_is_not_taken(engine):
    s, trade_id, _ = open_trade(engine)
    action_id = tap(engine, "skipped")
    assert s.newly_taken_trade_ids(0) == ([], action_id)
    assert not s.is_taken(trade_id)


def test_events_update_trade_and_alert_only_when_taken(engine):
    s, trade_id, _ = open_trade(engine)
    s.emit_event(ev("partial_exit", trade_id, 102.0, 60, 2.0), taken=False)
    s.emit_event(ev("trail_update", trade_id, 102.0, 0, 0.0), taken=False)
    t = rows(engine, paper_trades)[0]
    assert t["partial_exit_price"] == 102.0 and t["exit_ts"] is None
    assert len(rows(engine, alerts)) == 1
    s.emit_event(ev("runner_exit", trade_id, 103.0, 40, 3.0, 10, 30), taken=True)
    t = rows(engine, paper_trades)[0]
    assert t["exit_reason"] == "runner_exit" and t["exit_price"] == 103.0
    assert t["exit_ts"] == datetime(2026, 9, 15, 10, 30, tzinfo=IST).isoformat()
    assert t["gross_r"] == pytest.approx(0.6 * 2 + 0.4 * 3)
    assert t["net_r"] == pytest.approx(2.4 - 50 / 100)
    assert [a["alert_type"] for a in rows(engine, alerts)] == ["entry", "event"]


def test_single_qty_partial_closes_trade(engine):
    s = sink(engine)
    sig = make_signal(ts=at(9, 35))
    sid = s.record_signal(sig)
    trade_id = s.accept(make_plan(sig, qty=1), sid)
    s.emit_event(ev("partial_exit", trade_id, 102.0, 1, 2.0), taken=False)
    t = rows(engine, paper_trades)[0]
    assert t["exit_reason"] == "partial_exit" and t["net_r"] == pytest.approx(2.0 - 50)
