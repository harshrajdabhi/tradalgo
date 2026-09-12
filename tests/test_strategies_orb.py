import pytest

from tests.strategy_fixtures import append_future, at, ctx_at, with_today
from tradalgo.indicators import atr
from tradalgo.strategies.common import bounded_stop
from tradalgo.strategies.orb import orb

OR_ROWS = [
    (100.0, 100.8, 99.6, 100.4, 1000),
    (100.4, 101.0, 100.0, 100.8, 1000),
    (100.8, 101.0, 100.2, 100.6, 1000),
    (100.6, 101.0, 100.2, 100.9, 1000),
]
TRIGGER = (100.9, 101.4, 100.8, 101.2, 2000)


def test_orb_long_trigger():
    ctx = ctx_at(with_today(OR_ROWS + [TRIGGER]), at(9, 40))
    sig = orb(ctx)
    assert sig is not None and sig.direction == "long" and sig.strategy == "orb"
    assert sig.ts == at(9, 35)
    assert sig.entry == pytest.approx(101.2)
    assert sig.stop_loss == pytest.approx(99.6)  # OR low, 1.6 within [0.5, 2.0] x ATR
    assert 0.8 < atr(ctx.candles_5m).iloc[-1] < 1.1
    assert sig.features["or_high"] == 101.0 and sig.features["rvol"] == pytest.approx(2.0)
    assert not sig.counter_trend


def test_orb_short_trigger():
    trig = (100.3, 100.4, 99.3, 99.4, 3000)
    sig = orb(ctx_at(with_today(OR_ROWS + [trig]), at(9, 40)))
    assert sig.direction == "short" and sig.entry == pytest.approx(99.4)
    assert sig.stop_loss == pytest.approx(101.0)


def test_orb_no_trigger_low_rvol():
    assert orb(ctx_at(with_today(OR_ROWS + [TRIGGER[:4] + (1000,)]), at(9, 40))) is None


def test_orb_no_trigger_before_range_complete():
    assert orb(ctx_at(with_today(OR_ROWS[:3]), at(9, 30))) is None


def test_orb_does_not_refire():
    rows = OR_ROWS + [TRIGGER, (101.2, 101.6, 101.0, 101.5, 2500)]
    assert orb(ctx_at(with_today(rows), at(9, 45))) is None


def test_orb_no_lookahead():
    c5 = with_today(OR_ROWS + [TRIGGER])
    assert orb(ctx_at(append_future(c5), at(9, 40))) == orb(ctx_at(c5, at(9, 40)))
    assert orb(ctx_at(append_future(with_today(OR_ROWS)), at(9, 35))) is None


def test_bounded_stop():
    assert bounded_stop(100.0, 90.0, 1.0, "long") == 98.0
    assert bounded_stop(100.0, 99.9, 1.0, "long") == 99.5
    assert bounded_stop(100.0, 101.2, 1.0, "short") == 101.2
    assert bounded_stop(100.0, 99.0, 1.0, "short") == 100.5
