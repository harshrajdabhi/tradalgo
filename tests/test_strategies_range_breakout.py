import pytest

from tests.strategy_fixtures import append_future, at, ctx_at, with_today
from tradalgo.strategies.range_breakout import range_breakout

BOX = [(100.0, 100.3, 99.7, 100.1 if i % 2 else 99.9, 1000) for i in range(8)]
TRIGGER = (100.1, 101.0, 100.0, 100.9, 2000)


def test_range_breakout_long():
    sig = range_breakout(ctx_at(with_today(BOX + [TRIGGER]), at(10, 0)))
    assert sig.direction == "long" and sig.ts == at(9, 55)
    assert sig.entry == pytest.approx(100.9) and sig.stop_loss == pytest.approx(99.7)
    assert sig.features["range_high"] == 100.3


def test_range_breakout_no_trigger_low_rvol():
    assert range_breakout(ctx_at(with_today(BOX + [TRIGGER[:4] + (1000,)]), at(10, 0))) is None


def test_range_breakout_no_trigger_wide_range():
    wide = BOX[:4] + [(100.0, 102.5, 99.7, 100.1, 1000)] + BOX[5:]
    assert range_breakout(ctx_at(with_today(wide + [TRIGGER]), at(10, 0))) is None


def test_range_breakout_does_not_refire():
    rows = BOX + [TRIGGER, (100.9, 101.3, 100.8, 101.2, 2000)]
    assert range_breakout(ctx_at(with_today(rows), at(10, 5))) is None


def test_range_breakout_failed_breakout_retest_does_not_refire():
    rows = BOX + [TRIGGER, (100.5, 100.6, 100.0, 100.2, 1000), (100.2, 101.4, 100.1, 101.3, 2000)]
    assert range_breakout(ctx_at(with_today(rows), at(10, 10))) is None


def test_range_breakout_new_box_later_may_fire():
    new_box = [(100.0, 100.3, 99.7, 100.1 if i % 2 else 99.9, 1000) for i in range(8)]
    rows = BOX + [TRIGGER] + new_box + [TRIGGER]
    sig = range_breakout(ctx_at(with_today(rows), at(10, 45)))
    assert sig is not None and sig.direction == "long" and sig.ts == at(10, 40)
    assert sig.stop_loss == pytest.approx(99.7) and sig.features["range_high"] == 100.3


def test_range_breakout_no_lookahead():
    c5 = with_today(BOX + [TRIGGER])
    assert range_breakout(ctx_at(append_future(c5), at(10, 0))) == range_breakout(ctx_at(c5, at(10, 0)))
