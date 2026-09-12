from datetime import timedelta

import pandas as pd
import pytest

from tradalgo.clock import MarketCalendar
from tradalgo.engine.cycle import CycleDeps, SessionState, SymbolFrames, build_context, register_taken, run_cycle
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
    assert st.risk.realized_r == pytest.approx(-1.0 - 50 / (st.trades[101]["qty"] * 1.0))


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
    assert st.risk.trades_taken == (1 if taken else 0)
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
