from datetime import timedelta

import pandas as pd
import pytest

from tradalgo.clock import MarketCalendar
from tradalgo.engine.cycle import CycleDeps, SessionState, SymbolFrames, build_context, register_taken, run_cycle
from tradalgo.risk.costs import intraday_charges
from tradalgo.risk.plan import Rejection, TradePlan
from tradalgo.risk.validator import validate
from tests.backtest_fixtures import TODAY, at, bars, daily_trend, fake_classify, make_signal, rising_day, trading_weekdays

EMPTY = pd.DataFrame(columns=["open", "high", "low", "close", "volume"],
                     index=pd.DatetimeIndex([], tz="Asia/Kolkata", name="ts"), dtype=float)


class Sink:
    def __init__(self, taken=True):
        self.taken = taken
        self.signals, self.decisions, self.accepted, self.events = [], [], [], []

    def record_signal(self, signal):
        self.signals.append(signal)
        return len(self.signals)

    def record_decision(self, signal_id, decision):
        self.decisions.append(decision)

    def accept(self, plan, signal_id):
        self.accepted.append(plan)
        return 100 + len(self.accepted)

    def emit_event(self, event, taken):
        self.events.append((event, taken))

    def is_taken(self, trade_id):
        return self.taken


def flat(n_bars: int, price=100.0) -> pd.DataFrame:
    return bars(at(9, 15), [(price, price + 0.2, price - 0.2, price, 1000)] * n_bars)


def frames(symbols, df):
    return {s: SymbolFrames(df, EMPTY) for s in symbols}


@pytest.fixture
def deps_for(settings):
    def make(detect, data_dir=None):
        s = settings
        if data_dir is not None:
            s = settings.model_copy(update={"paths": settings.paths.model_copy(update={"data_dir": data_dir})})
        return CycleDeps(settings=s, calendar=MarketCalendar(s.market, set()), classify=fake_classify,
                         detect_all=detect, validate=validate, levels=lambda daily, c5, now: [])
    return make


def detector(signals_by_now):
    return lambda ctx, settings, calendar: [s for s in signals_by_now.get(ctx.now, []) if s.symbol == ctx.symbol]


def state():
    return SessionState.new(TODAY, 20000.0)


def test_accepted_signal_opens_position(deps_for):
    sig = make_signal(ts=at(9, 35))
    sink, st = Sink(), state()
    run_cycle(st, at(9, 40), frames(["AAA"], flat(5)), flat(5),
              deps_for(detector({at(9, 40): [sig]})), sink, check_kill_switch=False)
    assert len(sink.accepted) == 1 and isinstance(sink.decisions[0], TradePlan)
    assert len(st.position_manager["AAA"].open_trades()) == 1
    assert st.risk.trades_taken == 1 and st.taken_trade_ids == {101}


def test_frames_passed_to_detectors_hold_only_closed_candles(deps_for):
    seen = []
    deps = deps_for(lambda ctx, s, c: seen.append(ctx.candles_5m.index[-1]) or [])
    run_cycle(state(), at(9, 40), frames(["AAA"], flat(10)), flat(10), deps, Sink(),
              check_kill_switch=False)
    assert seen == [pd.Timestamp(at(9, 35))]


def test_duplicate_signal_not_recorded_again(deps_for):
    sig = make_signal(ts=at(9, 35))
    deps = deps_for(detector({at(9, 40): [sig], at(9, 45): [sig]}))
    sink, st = Sink(), state()
    for now, n in ((at(9, 40), 5), (at(9, 45), 6)):
        run_cycle(st, now, frames(["AAA"], flat(n)), flat(n), deps, sink,
                  check_kill_switch=False)
    assert len(sink.signals) == 1


def test_kill_switch_blocks_entries_but_manages_open_trades(deps_for, tmp_path):
    first = make_signal("AAA", ts=at(9, 35))
    later = make_signal("BBB", ts=at(9, 40))
    deps = deps_for(detector({at(9, 40): [first], at(9, 45): [later]}), data_dir=tmp_path)
    sink, st = Sink(), state()
    run_cycle(st, at(9, 40), frames(["AAA", "BBB"], flat(5)), flat(5), deps, sink,
              check_kill_switch=True)
    (tmp_path / "KILL").touch()
    crash = pd.concat([flat(5), bars(at(9, 40), [(100, 100.1, 98.0, 98.5, 1000)])])
    run_cycle(st, at(9, 45), frames(["AAA", "BBB"], crash), crash, deps, sink,
              check_kill_switch=True)
    assert [s.symbol for s in sink.signals] == ["AAA"]
    assert [(e.kind, e.ts) for e, _ in sink.events] == [("stop_hit", at(9, 45))]
    m = st.trades[101]
    charges = intraday_charges(m["entry"] * m["qty"], (m["entry"] - 1.0) * m["qty"], deps.settings.costs)
    assert st.risk.realized_r == pytest.approx(-1.0 - charges / (m["qty"] * 1.0))


def test_daily_limit_rejects_third_trade(deps_for):
    sigs = [make_signal(s, ts=at(9, 35)) for s in ("AAA", "BBB", "CCC")]
    sink, st = Sink(), state()
    run_cycle(st, at(9, 40), frames(["AAA", "BBB", "CCC"], flat(5)), flat(5),
              deps_for(detector({at(9, 40): sigs})), sink, check_kill_switch=False)
    assert [type(d) for d in sink.decisions] == [TradePlan, TradePlan, Rejection]
    assert "max trades" in sink.decisions[2].reason


@pytest.mark.parametrize("taken", [True, False])
def test_taken_vs_not_taken_event_routing(deps_for, taken):
    sig = make_signal(ts=at(9, 35))
    deps = deps_for(detector({at(9, 40): [sig]}))
    sink, st = Sink(taken=taken), state()
    run_cycle(st, at(9, 40), frames(["AAA"], flat(5)), flat(5), deps, sink,
              check_kill_switch=False)
    crash = pd.concat([flat(5), bars(at(9, 40), [(100, 100.1, 98.0, 98.5, 1000)])])
    run_cycle(st, at(9, 45), frames(["AAA"], crash), crash, deps, sink,
              check_kill_switch=False)
    assert [t for _, t in sink.events] == [taken]
    # an unanswered entry alert still holds its provisional slot (C2); only a taken trade realizes R
    assert st.risk.trades_taken == 1
    assert st.taken_trade_ids == ({101} if taken else set())
    assert (st.risk.realized_r < 0) == taken


def test_register_taken_is_idempotent_and_state_roundtrips(deps_for):
    sig = make_signal(ts=at(9, 35))
    sink, st = Sink(taken=False), state()
    run_cycle(st, at(9, 40), frames(["AAA"], flat(5)), flat(5),
              deps_for(detector({at(9, 40): [sig]})), sink, check_kill_switch=False)
    register_taken(st, 101)
    register_taken(st, 101)
    assert st.risk.trades_taken == 1
    back = SessionState.from_dict(st.to_dict())
    assert back.risk == st.risk and back.taken_trade_ids == {101} and back.seen_signals == st.seen_signals
    assert len(back.position_manager["AAA"].open_trades()) == 1 and back.trades == st.trades


def test_build_context_identical_for_5_or_50_prior_sessions():
    days = trading_weekdays(51, TODAY)
    five_m = {n: pd.concat([rising_day(d, 100 + i) for i, d in enumerate(days)][-(n + 1):]) for n in (5, 50)}
    daily = daily_trend(days[:-1], 50, 1.0)
    now = at(10, 2)  # mid-bar: the 09:55 bar is still forming
    a, b = (build_context("AAA", now, five_m[n], daily, five_m[n], fake_classify(None), fake_classify(None))
            for n in (5, 50))
    for name in ("candles_5m", "candles_15m", "daily", "index_15m"):
        pd.testing.assert_frame_equal(getattr(a, name), getattr(b, name))
    assert sorted(set(a.candles_5m.index.date)) == days[-6:]
    assert a.candles_5m.index[-1] == pd.Timestamp(at(9, 55))
    assert a.candles_5m.index[0] == pd.Timestamp(at(9, 15, days[-6]))
    assert a.candles_15m.index[-1] == pd.Timestamp(at(9, 45))
    assert a.daily.index[-1].date() < TODAY


def test_classifier_gets_20_sessions_detectors_get_5(deps_for):
    days = trading_weekdays(61, TODAY)
    seen = {}
    for n in (20, 60):
        five = pd.concat([rising_day(d, 100 + i) for i, d in enumerate(days)][-(n + 1):])
        classified, detected = [], []

        def classify(c15, c5=None, **kw):
            classified.append((c15, c5))
            return fake_classify(c15)

        deps = deps_for(lambda ctx, s, c: detected.append(ctx) or [])
        deps.classify = classify
        run_cycle(state(), at(10, 2), {"AAA": SymbolFrames(five, EMPTY)}, five, deps, Sink(), check_kill_switch=False)
        seen[n] = (classified, detected)
    for n in (20, 60):
        classified, (ctx,) = seen[n]
        assert all(len(set(c5.index.date)) == 21 and len(set(c15.index.date)) == 21 for c15, c5 in classified)
        assert len(set(ctx.candles_5m.index.date)) == 6 and len(set(ctx.index_15m.index.date)) == 6
    for (a15, a5), (b15, b5) in zip(seen[20][0], seen[60][0]):
        pd.testing.assert_frame_equal(a15, b15)
        pd.testing.assert_frame_equal(a5, b5)
    pd.testing.assert_frame_equal(seen[20][1][0].candles_5m, seen[60][1][0].candles_5m)


def test_shared_route_events_used_for_ticks_matches_bar_routing(deps_for):
    from tradalgo.engine.cycle import route_events
    sig = make_signal(ts=at(9, 35))
    sink, st = Sink(taken=True), state()
    deps = deps_for(detector({at(9, 40): [sig]}))
    run_cycle(st, at(9, 40), frames(["AAA"], flat(5)), flat(5), deps, sink, check_kill_switch=False)
    pm = st.position_manager["AAA"]
    events = pm.on_price(at(9, 42), 98.9, 98.9, 98.9, False)
    route_events(st, pm, events, deps.settings, sink)
    assert [(e.kind, t) for e, t in sink.events] == [("stop_hit", True)]
    assert st.trades[101]["closed"] and st.risk.open_trade_symbols == []
    m = st.trades[101]
    charges = intraday_charges(m["entry"] * m["qty"], (m["entry"] - 1.1) * m["qty"], deps.settings.costs)
    assert st.risk.realized_r == pytest.approx(-1.1 - charges / (m["qty"] * 1.0))


def test_open_position_registers_trade_and_seen_key(settings):
    from tradalgo.engine.cycle import open_position
    from tests.backtest_fixtures import make_plan
    st = state()
    open_position(st, make_plan(make_signal(ts=at(9, 35)), qty=10), 7, settings)
    assert st.trades[7]["qty"] == 10 and len(st.position_manager["AAA"].open_trades()) == 1


def test_missed_bars_are_replayed_so_a_skipped_bar_stop_still_alerts(deps_for):
    """C1: a sleep/restart backlog must not skip bars — the stop hit at 09:40-09:45 must still fire."""
    sig = make_signal(ts=at(9, 35))
    sink, st = Sink(), state()
    deps = deps_for(detector({at(9, 40): [sig]}))
    run_cycle(st, at(9, 40), frames(["AAA"], flat(5)), flat(5), deps, sink, check_kill_switch=False)
    # the 09:45 cycle never ran: at 09:50 both the 09:40 bar (low 97, stop breached) and the 09:45 bar are closed
    late = pd.concat([flat(5), bars(at(9, 40), [(100, 100.1, 97.0, 99.5, 1000), (101, 101.5, 101.0, 101.2, 1000)])])
    run_cycle(st, at(9, 50), frames(["AAA"], late), late, deps, sink, check_kill_switch=False)
    assert [(e.kind, e.ts) for e, _ in sink.events] == [("stop_hit", at(9, 45))]
    assert not st.position_manager["AAA"].open_trades()


def test_single_bar_per_cycle_is_not_double_processed(deps_for):
    sig = make_signal(ts=at(9, 35))
    sink, st = Sink(), state()
    deps = deps_for(detector({at(9, 40): [sig]}))
    run_cycle(st, at(9, 40), frames(["AAA"], flat(5)), flat(5), deps, sink, check_kill_switch=False)
    for n, now in ((6, at(9, 45)), (7, at(9, 50))):
        df = pd.concat([flat(5), bars(at(9, 40), [(100, 100.2, 99.8, 100.0, 1000)] * (n - 5))])
        run_cycle(st, now, frames(["AAA"], df), df, deps, sink, check_kill_switch=False)
    assert sink.events == []
    assert len(st.position_manager["AAA"].open_trades()) == 1


def test_entry_alerts_in_one_cycle_are_capped_before_the_user_answers(deps_for):
    """C2: with max_trades_per_day=2 only two entry alerts go out in a single cycle, even unanswered."""
    sigs = [make_signal(s, ts=at(9, 35)) for s in ("AAA", "BBB", "CCC")]
    sink, st = Sink(taken=False), state()
    run_cycle(st, at(9, 40), frames(["AAA", "BBB", "CCC"], flat(5)), flat(5),
              deps_for(detector({at(9, 40): sigs})), sink, check_kill_switch=False)
    assert [type(d) for d in sink.decisions] == [TradePlan, TradePlan, Rejection]
    assert "max trades" in sink.decisions[2].reason
    assert len(sink.accepted) == 2 and st.risk.trades_taken == 2
    assert st.reserved_trade_ids == {101, 102} and st.taken_trade_ids == set()


def test_skipped_entry_releases_the_reserved_slot(deps_for):
    from tradalgo.engine.cycle import release_slot
    sigs = [make_signal(s, ts=at(9, 35)) for s in ("AAA", "BBB")]
    sink, st = Sink(taken=False), state()
    deps = deps_for(detector({at(9, 40): sigs, at(9, 45): [make_signal("CCC", ts=at(9, 40))]}))
    run_cycle(st, at(9, 40), frames(["AAA", "BBB", "CCC"], flat(5)), flat(5), deps, sink, check_kill_switch=False)
    release_slot(st, 101)
    release_slot(st, 102)
    assert st.risk.trades_taken == 0 and st.risk.open_trade_symbols == [] and st.risk.taken == []
    df = pd.concat([flat(5), bars(at(9, 40), [(100, 100.2, 99.8, 100.0, 1000)])])
    run_cycle(st, at(9, 45), frames(["AAA", "BBB", "CCC"], df), df, deps, sink, check_kill_switch=False)
    assert isinstance(sink.decisions[-1], TradePlan) and len(sink.accepted) == 3


def test_taken_after_reservation_does_not_double_count(deps_for):
    sig = make_signal(ts=at(9, 35))
    sink, st = Sink(taken=False), state()
    run_cycle(st, at(9, 40), frames(["AAA"], flat(5)), flat(5),
              deps_for(detector({at(9, 40): [sig]})), sink, check_kill_switch=False)
    assert st.risk.trades_taken == 1 and st.reserved_trade_ids == {101}
    register_taken(st, 101)
    register_taken(st, 101)
    assert st.risk.trades_taken == 1 and st.taken_trade_ids == {101} and st.reserved_trade_ids == set()
    assert st.risk.open_trade_symbols == ["AAA"] and len(st.risk.taken) == 1
    back = SessionState.from_dict(st.to_dict())
    assert back.risk == st.risk and back.reserved_trade_ids == set()
