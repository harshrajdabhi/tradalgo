import pytest

from tests.strategy_fixtures import append_future, at, ctx_at, with_today
from tradalgo.strategies.base import Regime
from tradalgo.strategies.vwap import vwap

RECLAIM_BASE = [
    (100.0, 100.5, 99.5, 100.0, 1000),
    (100.0, 100.2, 99.2, 99.4, 1000),
    (99.4, 99.5, 98.9, 99.1, 1000),
    (99.1, 99.3, 98.8, 99.0, 1000),
]
RECLAIM = (99.0, 100.2, 98.9, 100.1, 1000)

CONT_BASE = [
    (100.0, 100.6, 99.8, 100.5, 1000),
    (100.5, 101.2, 100.4, 101.0, 1000),
    (101.0, 101.6, 101.0, 101.4, 1000),
]
CONT = (101.4, 101.5, 100.6, 101.3, 1000)

REJ_BASE = [
    (100.0, 100.5, 99.0, 99.2, 3000),
    (99.2, 99.3, 98.5, 98.6, 1000),
    (98.6, 98.9, 98.5, 98.8, 1000),
    (98.8, 99.1, 98.7, 99.0, 1000),
]
REJ = (99.0, 99.8, 98.9, 99.05, 1000)


def test_vwap_reclaim_long():
    sig = vwap(ctx_at(with_today(RECLAIM_BASE + [RECLAIM]), at(9, 40)))
    assert sig.direction == "long" and sig.features["variant"] == "reclaim" and not sig.counter_trend
    assert sig.entry == pytest.approx(100.1) and sig.stop_loss == pytest.approx(98.8)
    typicals = [(h + l + c) / 3 for _, h, l, c, _ in RECLAIM_BASE + [RECLAIM]]
    assert sig.features["vwap"] == pytest.approx(sum(typicals) / 5)


def test_vwap_continuation_long_in_trend():
    sig = vwap(ctx_at(with_today(CONT_BASE + [CONT]), at(9, 35), regime=Regime.TREND_UP))
    assert sig.direction == "long" and sig.features["variant"] == "continuation"
    assert sig.entry == pytest.approx(101.3) and sig.stop_loss == pytest.approx(100.6)


def test_vwap_continuation_needs_trend_regime():
    assert vwap(ctx_at(with_today(CONT_BASE + [CONT]), at(9, 35), regime=Regime.RANGE)) is None


def test_vwap_rejection_short_is_counter_trend():
    sig = vwap(ctx_at(with_today(REJ_BASE + [REJ]), at(9, 40)))
    assert sig.direction == "short" and sig.counter_trend and sig.features["variant"] == "rejection"
    assert sig.entry == pytest.approx(99.05) and sig.stop_loss == pytest.approx(99.8)


def test_vwap_no_trigger():
    assert vwap(ctx_at(with_today(RECLAIM_BASE + [(99.0, 99.3, 98.9, 99.2, 1000)]), at(9, 40))) is None


def test_vwap_does_not_refire():
    rows = RECLAIM_BASE + [RECLAIM, (100.1, 100.4, 99.9, 100.3, 1000)]
    assert vwap(ctx_at(with_today(rows), at(9, 45))) is None
    rows = CONT_BASE + [CONT, (101.3, 101.4, 100.9, 101.35, 1000)]
    assert vwap(ctx_at(with_today(rows), at(9, 40), regime=Regime.TREND_UP)) is None


def test_vwap_no_lookahead():
    c5 = with_today(RECLAIM_BASE + [RECLAIM])
    assert vwap(ctx_at(append_future(c5), at(9, 40))) == vwap(ctx_at(c5, at(9, 40)))
