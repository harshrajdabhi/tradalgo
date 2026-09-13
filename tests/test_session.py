import json
from datetime import date, datetime

import pytest
from sqlalchemy import insert, select

from tradalgo.clock import IST
from tradalgo.engine.live_sink import LiveSink
from tradalgo.engine.session import LiveSession, in_window, poll_telegram_updates, schedule, status_text_for
from tradalgo.storage.schema import alerts, health_events, job_runs, paper_trades, signals, user_actions
from tests.backtest_fixtures import TODAY, at, make_signal
from tests.session_fixtures import (FakeProvider, calendar, cycle_times, detector, fake_classify, frames, make_cache,
                                    make_db)


class Clk:
    def __init__(self, dt):
        self.dt = dt

    def now(self):
        return self.dt


class FakeStream:
    def __init__(self, on_tick):
        self.on_tick = on_tick
        self.subscribed, self.unsubscribed = set(), set()
        self.started = self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def subscribe(self, symbols):
        self.subscribed |= set(symbols)

    def unsubscribe(self, symbols):
        self.unsubscribed |= set(symbols)


@pytest.fixture
def env(settings, tmp_path):
    s = settings.model_copy(update={"paths": settings.paths.model_copy(update={"data_dir": tmp_path})})
    return s, make_db(tmp_path), tmp_path


def make_session(env, provider=None, extra=None, streams=None, clock=None, sink_cls=LiveSink):
    s, engine, tmp = env
    cache = make_cache(tmp, provider or FakeProvider(frames()))
    clock = clock or Clk(at(9, 20))
    streams = streams if streams is not None else []
    factory = lambda on_tick: streams.append(FakeStream(on_tick)) or streams[-1]
    session = LiveSession(s, engine, clock, cache.provider, cache,
                          lambda degraded_fn: sink_cls(engine, clock, degraded_fn, True),
                          tick_stream_factory=factory, state_dir=tmp / "state", calendar=calendar(s),
                          cycle_overrides={"classify": fake_classify, "detect_all": detector(extra),
                                           "levels": lambda daily, c5, now: []})
    return session, clock


def run(session, clock, start, end, hook=None):
    for t in cycle_times(start, end):
        clock.dt = t
        if hook:
            hook(t)
        session.run_once(t)


def q(engine, table):
    with engine.connect() as conn:
        return conn.execute(select(table).order_by(table.c.id)).mappings().all()


def tap(engine, action="taken", ts=None):
    entry = [a for a in q(engine, alerts) if a["alert_type"] == "entry"][0]
    with engine.begin() as conn:
        conn.execute(insert(user_actions).values(alert_id=entry["id"], action=action,
                                                 ts=(ts or at(9, 42)).isoformat()))


def kinds(engine):
    return [a["dedup_key"].split(":")[0] for a in q(engine, alerts)]


def test_shadow_day_taken_alert_sequence(env):
    _, engine, tmp = env
    session, clock = make_session(env)
    assert session.start(TODAY)
    run(session, clock, at(9, 20), at(9, 40))
    tap(engine)
    run(session, clock, at(9, 45), at(15, 30))
    ks = kinds(engine)
    assert ks[0] == "entry" and ks[1] == "partial_exit" and ks[-1] == "hard_exit"
    assert set(ks[2:-1]) == {"trail_update"} and len(ks[2:-1]) >= 2
    rows = q(engine, alerts)
    assert {a["status"] for a in rows} == {"queued"}
    assert len({(a["dedup_key"]) for a in rows}) == len(rows)
    trade = q(engine, paper_trades)[0]
    assert trade["taken_by_user"] == 1 and trade["exit_reason"] == "hard_exit"
    assert session.state.risk.trades_taken == 1
    assert session.state.risk.realized_r == pytest.approx(trade["net_r"])
    assert trade["mfe_r"] > 2 and trade["mae_r"] <= 0
    assert len(q(engine, signals)) == 1

    clock.dt = at(15, 31)
    session.finish(at(15, 31))
    session.finish(at(15, 31))
    eod = [a for a in q(engine, alerts) if a["dedup_key"] == f"eod:{TODAY.isoformat()}"]
    assert len(eod) == 1 and "Taken: 1" in eod[0]["text"]
    assert q(engine, job_runs)[-1]["status"] == "succeeded"


@pytest.mark.parametrize("action", ["skipped", None])
def test_skipped_or_ignored_gets_entry_only_but_trade_is_tracked(env, action):
    _, engine, _ = env
    session, clock = make_session(env)
    session.start(TODAY)
    run(session, clock, at(9, 20), at(9, 40))
    if action:
        tap(engine, action)
    run(session, clock, at(9, 45), at(15, 30))
    assert kinds(engine) == ["entry"]
    trade = q(engine, paper_trades)[0]
    assert trade["taken_by_user"] == 0 and trade["exit_reason"] == "hard_exit" and trade["partial_exit_ts"]
    assert session.state.risk.trades_taken == 0 and session.state.risk.realized_r == 0


def test_crash_recovery_does_not_duplicate_and_keeps_managing(env):
    _, engine, tmp = env
    session, clock = make_session(env)
    session.start(TODAY)
    run(session, clock, at(9, 20), at(9, 40))
    tap(engine)
    run(session, clock, at(9, 45), at(11, 0))
    assert (tmp / "state" / f"session_state_{TODAY.isoformat()}.json").exists()
    del session
    fresh, clock = make_session(env, clock=Clk(at(11, 5)))
    assert fresh.start(TODAY)
    fresh.run_once(at(11, 5))
    assert len(q(engine, signals)) == 1 and kinds(engine).count("entry") == 1
    assert f"trail_update:1:{at(11, 5).isoformat()}" in {a["dedup_key"] for a in q(engine, alerts)}
    assert fresh.state.risk.trades_taken == 1


def test_kill_switch_blocks_entries_but_manages_taken_trade(env):
    _, engine, tmp = env
    extra = {at(9, 50): [make_signal("BBB", "vwap", ts=at(9, 45))]}
    session, clock = make_session(env, extra=extra)
    session.start(TODAY)
    run(session, clock, at(9, 20), at(9, 40))
    tap(engine)
    (tmp / "KILL").touch()
    run(session, clock, at(9, 45), at(10, 0))
    assert [r["symbol"] for r in q(engine, signals)] == ["AAA"]
    assert kinds(engine)[:2] == ["entry", "partial_exit"]


def test_degraded_provider_marks_entry_and_warns_once(env):
    _, engine, _ = env
    session, clock = make_session(env, provider=FakeProvider(frames(), degraded=True))
    session.start(TODAY)
    run(session, clock, at(9, 20), at(9, 50))
    assert "DEGRADED" in q(engine, alerts)[0]["text"]
    warns = [h for h in q(engine, health_events) if h["component"] == "data" and h["level"] == "warning"]
    assert len(warns) == 1


def test_cycle_exception_is_recorded_and_next_cycle_works(env):
    _, engine, _ = env
    provider = FakeProvider(frames())
    session, clock = make_session(env, provider=provider)
    session.start(TODAY)
    provider.fail_next = True
    session.run_once(at(9, 40))
    errors = [h for h in q(engine, health_events) if h["component"] == "session" and h["level"] == "error"]
    assert len(errors) == 1 and "boom" in errors[0]["message"]
    clock.dt = at(9, 45)
    session.run_once(at(9, 45))
    assert kinds(engine)[0] == "entry"


def test_tick_stop_between_cycles_alerts_once(env):
    _, engine, _ = env
    streams = []
    session, clock = make_session(env, provider=FakeProvider(frames(stop_bar=True)), streams=streams)
    session.start(TODAY)
    run(session, clock, at(9, 20), at(9, 40))
    assert streams[0].started and streams[0].subscribed == {"AAA"}
    tap(engine)
    clock.dt = at(9, 42)
    streams[0].on_tick("AAA", datetime(2026, 9, 15, 9, 42, 5, tzinfo=IST), 98.9)
    assert kinds(engine) == ["entry", "stop_hit"]
    run(session, clock, at(9, 45), at(10, 0))
    assert kinds(engine) == ["entry", "stop_hit"]
    assert streams[0].unsubscribed == {"AAA"}
    assert session.state.risk.trades_taken == 1 and session.state.risk.realized_r < -1


def test_start_skips_non_trading_day_and_empty_shortlist(env):
    _, engine, _ = env
    session, _ = make_session(env)
    assert not session.start(date(2026, 9, 19))
    assert not session.start(date(2026, 9, 16))
    assert any(h["component"] == "session" and h["level"] == "warning" for h in q(engine, health_events))
    assert session.start(TODAY) and session.symbols == ["AAA", "BBB"]


def test_schedule_registers_cycle_and_finish_jobs(env):
    session, _ = make_session(env)

    class Sched:
        def __init__(self):
            self.jobs = []

        def add_job(self, func, trigger, **kw):
            self.jobs.append((func, trigger, kw))

    sched = Sched()
    schedule(session, sched)
    cycle = str(sched.jobs[0][1])
    assert "minute='*/5'" in cycle and "second='10'" in cycle and "hour='9-15'" in cycle
    assert "hour='15'" in str(sched.jobs[1][1]) and "minute='31'" in str(sched.jobs[1][1])
    assert not in_window(at(9, 15)) and in_window(at(9, 20)) and in_window(datetime(2026, 9, 15, 15, 30, 10, tzinfo=IST))
    assert not in_window(at(15, 35))


class FakeTelegram:
    def __init__(self):
        self.offsets, self.sent = [], []

    def get_updates(self, offset, timeout=0):
        self.offsets.append(offset)
        return [{"update_id": 41, "message": {"chat": {"id": 7}, "text": "/status"}}] if offset == 0 else []

    def send_message(self, text, buttons=None):
        self.sent.append(text)
        return 1


def test_poll_telegram_updates_persists_offset(env):
    s, engine, tmp = env
    client, path = FakeTelegram(), tmp / "tg_offset.json"
    status = status_text_for(engine, Clk(at(10, 0)), tmp / "state", data_dir=tmp)
    assert poll_telegram_updates(engine, client, Clk(at(10, 0)), tmp, 7, status, path) == 42
    assert poll_telegram_updates(engine, client, Clk(at(10, 0)), tmp, 7, status, path) == 42
    assert client.offsets == [0, 42] and json.loads(path.read_text())["offset"] == 42
    assert "AAA" in client.sent[0] and "Kill switch: off" in client.sent[0]


def test_each_cycle_refetches_todays_bars_through_the_real_cache(env):
    _, engine, tmp = env
    provider = FakeProvider(frames())
    session, clock = make_session(env, provider=provider)
    session.start(TODAY)
    provider.cutoff = clock.dt = at(9, 40).replace(second=30)
    session.run_once(at(9, 40))
    tap(engine)
    provider.cutoff = clock.dt = at(9, 50).replace(second=5)
    session.run_once(at(9, 50))
    assert kinds(engine)[:2] == ["entry", "partial_exit"]
    assert max(session.cache.load("AAA", "5m").index.date) < TODAY   # today's partial bars never persisted


class CrashAfter(LiveSink):
    """Simulates the process dying right after a DB write, before the session saves its state."""
    crash_on: str = "accept"

    def accept(self, plan, signal_id):
        trade_id = super().accept(plan, signal_id)
        if self.crash_on == "accept":
            raise SystemExit("crash")
        return trade_id

    def emit_event(self, event, taken):
        super().emit_event(event, taken)
        if self.crash_on == "exit" and event.kind == "stop_hit":
            raise SystemExit("crash")


def crash_run(session, clock, start, end):
    try:
        run(session, clock, start, end)
    except SystemExit:
        pass


def test_crash_between_accept_and_save_adopts_the_db_trade(env):
    _, engine, _ = env
    first, clock = make_session(env, sink_cls=CrashAfter)
    first.start(TODAY)
    crash_run(first, clock, at(9, 20), at(9, 40))
    fresh, clock = make_session(env, clock=Clk(at(9, 45)))
    assert fresh.start(TODAY)
    fresh.run_once(at(9, 45))
    tap(engine)
    run(fresh, clock, at(9, 50), at(10, 0))
    assert len(q(engine, signals)) == 1 and len(q(engine, paper_trades)) == 1
    assert kinds(engine).count("entry") == 1 and "partial_exit" in kinds(engine)
    assert fresh.state.risk.trades_taken == 1


def test_crash_after_exit_before_save_does_not_realert(env):
    _, engine, _ = env
    CrashExit = type("CrashExit", (CrashAfter,), {"crash_on": "exit"})
    first, clock = make_session(env, provider=FakeProvider(frames(stop_bar=True)), sink_cls=CrashExit)
    first.start(TODAY)
    run(first, clock, at(9, 20), at(9, 40))
    tap(engine)
    crash_run(first, clock, at(9, 45), at(9, 45))
    fresh, clock = make_session(env, provider=FakeProvider(frames(stop_bar=True)), clock=Clk(at(9, 50)))
    fresh.start(TODAY)
    run(fresh, clock, at(9, 50), at(10, 0))
    assert kinds(engine) == ["entry", "stop_hit"]
    assert fresh.state.risk.trades_taken == 1 and fresh.state.risk.realized_r < -1
    assert fresh.state.risk.open_trade_symbols == []
