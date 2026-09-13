from datetime import datetime, timedelta

import pytest

from tradalgo.clock import IST
from tradalgo.engine.positions import PositionManager
from tradalgo.risk.plan import TradePlan
from tradalgo.strategies.base import Regime, Signal

T0 = datetime(2026, 9, 11, 10, 0, tzinfo=IST)


def plan(direction="long", entry=100.0, stop=98.0, qty=10):
    s = Signal("SBIN", "orb", direction, T0, entry, stop, Regime.TREND_UP, Regime.TREND_UP, False, "t")
    return TradePlan(s, qty, 5.0, qty * entry / 5, qty * s.risk_per_share, s.target(2), s.target(3), 50.0,
                     99.0, 0.1, entry, entry, T0 + timedelta(minutes=10))


def at(h, m):
    return T0.replace(hour=h, minute=m)


def kinds(events):
    return [e.kind for e in events]


def test_2r_then_drift_to_hard_exit():
    pm = PositionManager()
    pm.open(1, plan())
    events = []
    events += pm.on_price(at(10, 5), 101.0, 99.5, 100.5, True)
    events += pm.on_price(at(10, 10), 104.2, 100.5, 104.0, True)
    for i, m in enumerate(range(15, 60, 5)):
        events += pm.on_price(at(10, m), 104.5, 103.0 + 0.05 * i, 104.0, True)
    events += pm.on_price(at(15, 0), 104.5, 103.8, 104.1, True)
    events += pm.on_price(at(15, 5), 104.5, 103.8, 104.1, True)
    ks = kinds(events)
    assert ks.count("partial_exit") == 1 and ks.count("hard_exit") == 1
    partial = events[ks.index("partial_exit")]
    assert (partial.qty, partial.price, partial.r_multiple) == (6, 104.0, 2.0)
    trails = [e for e in events if e.kind == "trail_update"]
    assert trails[0].new_stop == 100.0
    assert all(b.new_stop > a.new_stop for a, b in zip(trails, trails[1:]))
    hard = events[ks.index("hard_exit")]
    assert (hard.qty, hard.price) == (4, 104.1)
    assert hard.r_multiple == pytest.approx(2.05)
    assert pm.open_trades() == []


def test_breakeven_trail_is_single_without_trailing_bars():
    pm = PositionManager(trail_bars=3)
    pm.open(1, plan())
    ev = pm.on_price(at(10, 5), 104.0, 100.0, 103.0, False)
    assert kinds(ev) == ["partial_exit", "trail_update"]
    assert kinds(pm.on_price(at(10, 6), 103.5, 103.5, 103.5, False)) == []


def test_ambiguous_bar_is_stop_first():
    pm = PositionManager()
    pm.open(1, plan())
    ev = pm.on_price(at(10, 5), 106.5, 97.5, 101.0, True)
    assert kinds(ev) == ["stop_hit"]
    assert (ev[0].qty, ev[0].price, ev[0].r_multiple) == (10, 98.0, -1.0)
    assert pm.on_price(at(10, 10), 110.0, 90.0, 100.0, True) == []


def test_short_mirror():
    pm = PositionManager()
    pm.open(7, plan("short", 200.0, 204.0, qty=5))
    ev = pm.on_price(at(10, 5), 201.0, 191.5, 192.5, True)
    assert kinds(ev) == ["partial_exit", "trail_update"]
    assert (ev[0].qty, ev[0].price, ev[0].r_multiple) == (3, 192.0, 2.0)
    assert ev[1].new_stop == 200.0
    ev = pm.on_price(at(10, 10), 193.0, 187.0, 188.0, True)
    assert kinds(ev) == ["runner_exit"]
    assert (ev[0].qty, ev[0].price, ev[0].r_multiple) == (2, 188.0, 3.0)


def test_short_stop():
    pm = PositionManager()
    pm.open(7, plan("short", 200.0, 204.0, qty=5))
    ev = pm.on_price(at(10, 5), 204.0, 204.0, 204.0, False)
    assert kinds(ev) == ["stop_hit"] and ev[0].r_multiple == -1.0


def test_trail_never_loosens_long():
    pm = PositionManager(trail_bars=3)
    pm.open(1, plan())
    pm.on_price(at(10, 5), 103.0, 99.0, 102.0, True)
    ev = pm.on_price(at(10, 10), 104.0, 101.0, 103.9, True)     # partial, stop -> 100
    assert [e.new_stop for e in ev if e.kind == "trail_update"] == [100.0]
    ev = pm.on_price(at(10, 15), 104.5, 102.0, 104.0, True)     # lows 99,101,102 -> 99 would loosen
    assert ev == [] and pm.to_dict()["trades"][0]["stop"] == 100.0
    ev = pm.on_price(at(10, 20), 105.0, 103.0, 104.5, True)     # lows 101,102,103 -> 101
    assert [e.new_stop for e in ev if e.kind == "trail_update"] == [101.0]
    ev = pm.on_price(at(10, 21), 101.0, 101.0, 101.0, False)
    assert kinds(ev) == ["stop_hit"] and ev[0].qty == 4 and ev[0].r_multiple == 0.5


def test_trail_never_loosens_short():
    pm = PositionManager(trail_bars=2)
    pm.open(1, plan("short", 200.0, 204.0))
    pm.on_price(at(10, 5), 201.0, 192.0, 193.0, True)           # partial, stop -> 200
    ev = pm.on_price(at(10, 10), 197.0, 191.0, 192.0, True)     # highs 201,197 -> 201 looser
    assert ev == [] and pm.to_dict()["trades"][0]["stop"] == 200.0
    ev = pm.on_price(at(10, 15), 198.0, 190.0, 192.0, True)     # highs 197,198 -> 198
    assert [e.new_stop for e in ev if e.kind == "trail_update"] == [198.0]


def test_qty_one_exits_whole_at_2r():
    pm = PositionManager()
    pm.open(1, plan(qty=1))
    ev = pm.on_price(at(10, 5), 104.0, 101.0, 103.5, True)
    assert kinds(ev) == ["partial_exit"] and ev[0].qty == 1
    assert pm.open_trades() == []
    assert pm.on_price(at(15, 0), 105.0, 104.0, 104.5, True) == []


def test_replaying_same_bar_emits_nothing():
    pm = PositionManager()
    pm.open(1, plan())
    bar = (at(10, 5), 104.0, 100.0, 103.0, True)
    assert kinds(pm.on_price(*bar)) == ["partial_exit", "trail_update"]
    assert pm.on_price(*bar) == []
    assert pm.on_price(at(10, 0), 90.0, 90.0, 90.0, True) == []   # older data ignored
    hx = (at(15, 0), 103.0, 102.0, 102.5, True)
    assert kinds(pm.on_price(*hx)) == ["hard_exit"]
    assert pm.on_price(*hx) == []


def test_fill_price_does_not_change_r():
    pm = PositionManager()
    pm.open(1, plan(), filled_price=100.2)
    ev = pm.on_price(at(10, 5), 98.0, 98.0, 98.0, False)
    assert ev[0].r_multiple == -1.0


def test_round_trip_preserves_behaviour():
    def drive(pm, bars):
        return [(e.kind, e.qty, e.price, e.new_stop, e.r_multiple) for b in bars for e in pm.on_price(*b)]

    first = [(at(10, 5), 104.0, 101.0, 103.9, True), (at(10, 10), 104.5, 102.0, 104.0, True)]
    rest = [(at(10, 15), 105.0, 103.0, 104.5, True), (at(10, 20), 105.9, 104.0, 105.0, True),
            (at(10, 25), 106.1, 104.5, 106.0, True)]
    a = PositionManager()
    a.open(1, plan())
    a.open(2, plan("short", 200.0, 204.0))
    drive(a, first)
    b = PositionManager.from_dict(a.to_dict())
    assert b.to_dict() == a.to_dict()
    assert drive(b, first) == []
    assert drive(a, rest) == drive(b, rest)
    assert a.to_dict() == b.to_dict()


def test_late_closed_bar_after_ticks_is_processed():
    pm = PositionManager()
    pm.open(1, plan())
    assert pm.on_price(at(10, 6), 99.0, 99.0, 99.0, False) == []
    assert pm.on_price(at(10, 8), 98.5, 98.5, 98.5, False) == []
    bar = (at(10, 10), 99.5, 97.8, 98.6, True)                    # 10:05-10:10 bar stamped at close
    ev = pm.on_price(*bar)
    assert kinds(ev) == ["stop_hit"] and ev[0].price == 98.0
    assert pm.on_price(*bar) == []


def test_bar_at_same_ts_as_tick_is_processed_but_older_tick_ignored():
    pm = PositionManager(trail_bars=1)
    pm.open(1, plan())
    pm.on_price(at(10, 9), 104.0, 104.0, 104.0, False)             # partial, stop -> 100
    assert pm.on_price(at(10, 10), 104.1, 104.1, 104.1, False) == []
    ev = pm.on_price(at(10, 10), 104.5, 101.0, 104.0, True)         # bar at equal ts still trails
    assert [e.new_stop for e in ev if e.kind == "trail_update"] == [101.0]
    assert pm.on_price(at(10, 9), 90.0, 90.0, 90.0, False) == []


def test_gap_through_stop_fills_at_open():
    pm = PositionManager()
    pm.open(1, plan())
    ev = pm.on_price(at(10, 10), 97.0, 95.0, 96.0, True, open=96.5)
    assert kinds(ev) == ["stop_hit"] and ev[0].price == 96.5 and ev[0].r_multiple == pytest.approx(-1.75)


def test_gap_through_short_stop_and_tick_fill():
    pm = PositionManager()
    pm.open(1, plan("short", 200.0, 204.0))
    ev = pm.on_price(at(10, 6), 206.0, 206.0, 206.0, False)
    assert ev[0].price == 206.0 and ev[0].r_multiple == pytest.approx(-1.5)


def test_hard_exit_on_bar_closing_at_1500():
    pm = PositionManager()
    pm.open(1, plan())
    ev = pm.on_price(at(14, 55), 101.0, 99.0, 100.0, True)
    assert ev == []
    ev = pm.on_price(at(15, 0), 101.0, 99.0, 100.5, True)          # 14:55-15:00 bar stamped at close
    assert kinds(ev) == ["hard_exit"] and ev[0].qty == 10
    assert pm.on_price(at(15, 0), 101.0, 99.0, 100.5, True) == []
    assert pm.on_price(at(15, 1), 100.0, 100.0, 100.0, False) == []


def test_partial_and_3r_same_bar():
    pm = PositionManager()
    pm.open(1, plan())
    ev = pm.on_price(at(10, 10), 106.5, 99.0, 106.0, True)
    assert kinds(ev) == ["partial_exit", "trail_update", "runner_exit"]
    assert (ev[2].qty, ev[2].r_multiple) == (4, 3.0)


def test_tick_just_after_bar_close_does_not_swallow_that_bar():
    pm = PositionManager()
    pm.open(1, plan())
    assert pm.on_price(at(10, 10).replace(second=5), 99.0, 99.0, 99.0, False) == []
    ev = pm.on_price(at(10, 10), 99.5, 97.0, 98.5, True, open=99.0)   # cycle at 10:10:10 sees the breaching bar
    assert kinds(ev) == ["stop_hit"]
    assert pm.on_price(at(10, 10).replace(second=20), 98.0, 98.0, 98.0, False) == []
    assert pm.on_price(at(10, 10), 99.5, 97.0, 98.5, True) == []


def test_trail_advances_with_ticks_between_bars():
    pm = PositionManager(trail_bars=1)
    pm.open(1, plan())
    pm.on_price(at(10, 5), 104.0, 100.5, 103.0, True)                   # partial, stop -> 100
    pm.on_price(at(10, 10).replace(second=3), 103.5, 103.5, 103.5, False)
    ev = pm.on_price(at(10, 10), 104.5, 101.0, 104.0, True)
    assert [e.new_stop for e in ev if e.kind == "trail_update"] == [101.0]


def test_excursions_tracked_in_r_and_round_trip():
    pm = PositionManager()
    pm.open(1, plan())
    pm.on_price(at(10, 5), 101.0, 99.0, 100.0, True)
    pm.on_price(at(10, 6), 102.5, 102.5, 102.5, False)
    t = pm.trades()[0]
    assert (t.mfe_r, t.mae_r) == (pytest.approx(1.25), pytest.approx(-0.5))
    back = PositionManager.from_dict(pm.to_dict())
    assert back.trades()[0].mfe_r == pytest.approx(1.25)
