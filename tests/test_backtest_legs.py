import json
from datetime import timedelta

from sqlalchemy import inspect, select, text

from tradalgo.backtest.paper_broker import PaperBroker
from tradalgo.backtest.replay import BacktestSink
from tradalgo.config import CostsConfig
from tradalgo.engine.cycle import SymbolFrames
from tradalgo.engine.events import PositionEvent
from tradalgo.storage import repo
from tradalgo.storage.db import init_db, make_engine
from tradalgo.storage.schema import backtest_trades
from tests.backtest_fixtures import REPLAY_DAYS, at, bars, make_plan, make_signal, replay_params


def _columns(engine):
    return {c["name"] for c in inspect(engine).get_columns("backtest_trades")}


def test_init_db_adds_legs_json_to_an_old_database(tmp_path):
    engine = make_engine(tmp_path / "old.db")
    init_db(engine)
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE backtest_trades DROP COLUMN legs_json"))
    assert "legs_json" not in _columns(engine)
    init_db(engine)
    init_db(engine)  # idempotent
    assert "legs_json" in _columns(engine)


def test_sink_stores_every_leg_in_order(tmp_path):
    engine = make_engine(tmp_path / "t.db")
    init_db(engine)
    run_id = repo.enqueue_backtest_run(engine, replay_params(REPLAY_DAYS[0], REPLAY_DAYS[0]), at(8, 0))
    signal = make_signal(ts=at(9, 35), entry=100.0, stop=99.0)
    plan = make_plan(signal, qty=100)
    frames = {"AAA": SymbolFrames(bars(at(9, 35), [(100, 101, 99.5, 100.5, 1e5)] * 6), None)}
    sink = BacktestSink(engine, run_id, PaperBroker(0.05, CostsConfig()), frames)
    signal_id = sink.record_signal(signal)
    trade_id = sink.accept(plan, signal_id)

    def ev(kind, minutes, price, qty, new_stop, r):
        return PositionEvent(kind, trade_id, "AAA", "orb", at(9, 40) + timedelta(minutes=minutes), price, qty,
                             new_stop, r)

    sink.emit_event(ev("partial_exit", 5, 102.0, 60, None, 2.0), True)
    sink.emit_event(ev("trail_update", 5, 102.0, 0, 100.0, 0.0), True)
    sink.emit_event(ev("trail_update", 10, 102.5, 0, 101.0, 0.0), True)
    sink.emit_event(ev("stop_hit", 15, 101.0, 40, None, 1.0), True)

    with engine.connect() as conn:
        row = conn.execute(select(backtest_trades)).mappings().one()
    legs = json.loads(row["legs_json"])
    assert [leg["kind"] for leg in legs] == ["entry", "partial_exit", "trail_update", "trail_update", "stop_hit"]
    assert legs[0] == {"kind": "entry", "ts": at(9, 40).isoformat(), "price": 100.0, "qty": 100, "r": 0.0}
    assert legs[2] == {"kind": "trail_update", "ts": at(9, 45).isoformat(), "price": 102.0, "qty": 0, "r": 0.0,
                       "new_stop": 100.0}
    assert legs[4]["qty"] == 40 and legs[4]["r"] == 1.0 and "new_stop" not in legs[4]
    assert row["exit_reason"] == "stop_hit"
