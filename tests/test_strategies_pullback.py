import pytest

from tests.strategy_fixtures import append_future, at, ctx_at, with_today
from tradalgo.strategies.pullback import pullback

UP = [
    (100.0, 100.6, 99.9, 100.5, 1000),
    (100.5, 101.2, 100.4, 101.1, 1000),
    (101.1, 101.8, 101.0, 101.7, 1000),
    (101.7, 102.5, 101.6, 102.4, 1000),
    (102.4, 102.4, 101.5, 101.6, 1000),
    (101.6, 101.7, 101.1, 101.3, 1000),
]
TRIGGER = (101.3, 101.9, 101.2, 101.8, 1000)


def mirror(rows):
    return [(200 - o, 200 - l, 200 - h, 200 - c, v) for o, h, l, c, v in rows]


def test_pullback_long():
    sig = pullback(ctx_at(with_today(UP + [TRIGGER]), at(9, 50)))
    assert sig.direction == "long" and sig.ts == at(9, 45)
    assert sig.entry == pytest.approx(101.8) and sig.stop_loss == pytest.approx(101.1)


def test_pullback_short_mirror():
    sig = pullback(ctx_at(with_today(mirror(UP + [TRIGGER]), price=100.0), at(9, 50)))
    assert sig.direction == "short"
    assert sig.entry == pytest.approx(98.2) and sig.stop_loss == pytest.approx(98.9)


def test_pullback_no_trigger_without_break_of_prev_high():
    assert pullback(ctx_at(with_today(UP + [(101.3, 101.65, 101.2, 101.6, 1000)]), at(9, 50))) is None


def test_pullback_no_trigger_without_expansion():
    flat = [(100.0, 100.3, 99.8, 100.1, 1000), (100.1, 100.4, 99.9, 100.2, 1000), (100.2, 100.2, 99.9, 100.0, 1000),
            (100.0, 100.3, 99.9, 100.25, 1000)]
    assert pullback(ctx_at(with_today(flat), at(9, 35))) is None


def test_pullback_does_not_refire():
    rows = UP + [TRIGGER, (101.8, 102.2, 101.7, 102.1, 1000)]
    assert pullback(ctx_at(with_today(rows), at(9, 55))) is None


def test_pullback_no_lookahead():
    c5 = with_today(UP + [TRIGGER])
    assert pullback(ctx_at(append_future(c5), at(9, 50))) == pullback(ctx_at(c5, at(9, 50)))
