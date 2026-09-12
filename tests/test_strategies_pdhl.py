import pytest

from tests.strategy_fixtures import append_future, at, ctx_at, with_today
from tradalgo.strategies.pdhl import pdhl

BASE = [
    (100.0, 100.4, 99.8, 100.2, 1000),
    (100.2, 100.4, 100.0, 100.3, 1000),
    (100.3, 100.45, 100.1, 100.4, 1000),
]
BREAKOUT = (100.4, 101.2, 100.3, 101.0, 2000)
REJECTION = (100.4, 101.0, 100.3, 100.35, 1000)


def test_pdhl_breakout_long():
    ctx = ctx_at(with_today(BASE + [BREAKOUT]), at(9, 35))
    assert ctx.daily["high"].iloc[-1] == 100.5
    sig = pdhl(ctx)
    assert sig.direction == "long" and sig.features["variant"] == "breakout" and not sig.counter_trend
    assert sig.entry == pytest.approx(101.0) and sig.stop_loss == pytest.approx(100.3)
    assert sig.ts == at(9, 30) and sig.features["pdh"] == 100.5


def test_pdhl_rejection_short_is_counter_trend():
    sig = pdhl(ctx_at(with_today(BASE + [REJECTION]), at(9, 35)))
    assert sig.direction == "short" and sig.counter_trend and sig.features["variant"] == "rejection"
    assert sig.entry == pytest.approx(100.35) and sig.stop_loss == pytest.approx(101.0)


def test_pdhl_no_trigger_low_volume_breakout():
    assert pdhl(ctx_at(with_today(BASE + [BREAKOUT[:4] + (1000,)]), at(9, 35))) is None


def test_pdhl_does_not_refire():
    assert pdhl(ctx_at(with_today(BASE + [BREAKOUT, (101.0, 101.5, 100.9, 101.3, 2000)]), at(9, 40))) is None
    assert pdhl(ctx_at(with_today(BASE + [REJECTION, (100.35, 100.9, 100.2, 100.3, 1000)]), at(9, 40))) is None


def test_pdhl_no_lookahead():
    c5 = with_today(BASE + [BREAKOUT])
    assert pdhl(ctx_at(append_future(c5), at(9, 35))) == pdhl(ctx_at(c5, at(9, 35)))
