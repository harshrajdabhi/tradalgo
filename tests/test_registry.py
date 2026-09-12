from dataclasses import replace
from datetime import time

import pytest

from tests.conftest import ROOT
from tests.strategy_fixtures import at, ctx_at, with_today
from tests.test_strategies_orb import OR_ROWS, TRIGGER
from tests.test_strategies_pdhl import BASE, REJECTION
from tradalgo.clock import MarketCalendar, load_holidays
from tradalgo.strategies.base import Regime, Signal
from tradalgo.strategies.orb import orb
from tradalgo.strategies.registry import ALL_DETECTORS, REGIME_STRATEGIES, detect_all, market_alignment_ok

UP, DOWN = Regime.TREND_UP, Regime.TREND_DOWN


@pytest.fixture
def calendar(settings):
    return MarketCalendar(settings.market, load_holidays(ROOT / "data_static", 2026))


def orb_ctx(regime=UP, market=UP):
    return ctx_at(with_today(OR_ROWS + [TRIGGER]), at(9, 40), regime=regime, market_regime=market)


def names(signals):
    return {s.strategy for s in signals}


def test_all_detectors_match_config_keys(settings):
    assert set(ALL_DETECTORS) == set(settings.strategies)
    assert all(d.name == k for k, d in ALL_DETECTORS.items())
    assert REGIME_STRATEGIES[Regime.RANGE] == {"vwap", "range_breakout", "pdhl"}


def test_orb_fires_when_aligned(settings, calendar):
    assert "orb" in names(detect_all(orb_ctx(), settings, calendar))


def test_disabled_strategy_skipped(settings, calendar):
    settings.strategies["orb"] = settings.strategies["orb"].model_copy(update={"enabled": False})
    assert "orb" not in names(detect_all(orb_ctx(), settings, calendar))


def test_outside_entry_window_skipped(settings, calendar):
    settings.strategies["orb"] = settings.strategies["orb"].model_copy(update={"window_start": time(10, 0)})
    assert "orb" not in names(detect_all(orb_ctx(), settings, calendar))


def test_regime_gating(settings, calendar):
    assert "orb" not in names(detect_all(orb_ctx(regime=Regime.RANGE), settings, calendar))


def test_long_blocked_in_down_market(settings, calendar):
    assert "orb" not in names(detect_all(orb_ctx(market=DOWN), settings, calendar))


def test_long_blocked_in_stock_down_trend(settings, calendar):
    assert orb(orb_ctx(regime=DOWN, market=UP)).direction == "long"
    assert "orb" not in names(detect_all(orb_ctx(regime=DOWN, market=UP), settings, calendar))


def test_counter_trend_short_exempt_in_up_market(settings, calendar):
    ctx = ctx_at(with_today(BASE + [REJECTION]), at(9, 35), regime=UP, market_regime=UP)
    sigs = [s for s in detect_all(ctx, settings, calendar) if s.strategy == "pdhl"]
    assert len(sigs) == 1 and sigs[0].direction == "short" and sigs[0].counter_trend


def _sig(direction, regime, market, counter):
    entry, stop = (100.0, 99.0) if direction == "long" else (100.0, 101.0)
    return Signal("X", "orb", direction, at(9, 40), entry, stop, regime, market, counter, "t")


@pytest.mark.parametrize("direction, regime, market, counter, ok", [
    ("long", UP, UP, False, True),
    ("long", Regime.RANGE, DOWN, False, False),
    ("short", Regime.RANGE, UP, False, False),
    ("long", DOWN, Regime.RANGE, False, False),
    ("short", UP, Regime.HIGH_VOL, False, False),
    ("long", DOWN, DOWN, True, True),
    ("short", Regime.RANGE, Regime.RANGE, False, True),
])
def test_market_alignment_ok(direction, regime, market, counter, ok):
    assert market_alignment_ok(_sig(direction, regime, market, counter)) is ok
