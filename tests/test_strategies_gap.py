import pytest

from tests.strategy_fixtures import append_future, at, ctx_at, with_today
from tradalgo.strategies.gap import gap

FIRST15 = [
    (101.5, 102.0, 101.3, 101.8, 1000),
    (101.8, 102.1, 101.6, 102.0, 1000),
    (102.0, 102.2, 101.8, 102.1, 1000),
    (102.1, 102.2, 101.9, 102.0, 1000),
]
CONT = (102.0, 102.8, 101.95, 102.6, 1000)
FADE = (102.0, 102.1, 101.0, 101.1, 1000)


def test_gap_continuation_long():
    ctx = ctx_at(with_today(FIRST15 + [CONT]), at(9, 40))
    pc = ctx.daily["close"].iloc[-1]
    sig = gap(ctx)
    assert sig.direction == "long" and sig.features["variant"] == "continuation" and not sig.counter_trend
    assert sig.entry == pytest.approx(102.6) and sig.stop_loss == pytest.approx(101.3)
    assert sig.features["gap_pct"] == pytest.approx((101.5 - pc) / pc * 100)


def test_gap_fade_short_is_counter_trend():
    sig = gap(ctx_at(with_today(FIRST15 + [FADE]), at(9, 40)))
    assert sig.direction == "short" and sig.counter_trend and sig.features["variant"] == "fade"
    assert sig.entry == pytest.approx(101.1) and sig.stop_loss == pytest.approx(102.2)


def test_gap_too_small_no_trigger():
    rows = [tuple(v - 1.3 if i < 4 else v for i, v in enumerate(r)) for r in FIRST15 + [CONT]]
    assert gap(ctx_at(with_today(rows), at(9, 40))) is None


def test_gap_does_not_refire():
    assert gap(ctx_at(with_today(FIRST15 + [CONT, (102.6, 103.0, 102.5, 102.9, 1000)]), at(9, 45))) is None


def test_gap_no_lookahead():
    c5 = with_today(FIRST15 + [CONT])
    assert gap(ctx_at(append_future(c5), at(9, 40))) == gap(ctx_at(c5, at(9, 40)))
