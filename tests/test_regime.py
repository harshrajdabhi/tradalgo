import math

import pandas as pd

from tests.strategy_fixtures import TODAY, frame, at, history_5m, prior_days, sessions_15m
from tradalgo.regime import classify
from tradalgo.strategies.base import Regime

DAYS = prior_days(4) + [TODAY]


def trend(sign):
    def fn(k):
        p = 100 + sign * 0.3 * k
        return p - sign * 0.1, p + 0.3, p - 0.3, p + sign * 0.1
    return fn


def test_trend_up():
    assert classify(sessions_15m(DAYS, trend(1), last_day_bars=10)) == Regime.TREND_UP


def test_trend_down():
    assert classify(sessions_15m(DAYS, trend(-1), last_day_bars=10)) == Regime.TREND_DOWN


def test_range_on_oscillation():
    def fn(k):
        p = 100 + 2 * math.sin(k / 3)
        return p, p + 0.4, p - 0.4, p + 0.05
    assert classify(sessions_15m(DAYS, fn, last_day_bars=10)) == Regime.RANGE


def test_high_vol_takes_precedence_over_trend():
    calm = sessions_15m(DAYS, trend(1), last_day_bars=10)
    last = calm.index[-1]
    spike = frame((last + (calm.index[1] - calm.index[0])).to_pydatetime(), [
        (133.0, 150.0, 132.0, 149.0, 0.0),
    ], minutes=15)
    assert classify(calm) == Regime.TREND_UP
    assert classify(pd.concat([calm, spike])) == Regime.HIGH_VOL


def test_high_vol_from_atr_pct_percentile():
    def fn(k):
        p = 100 + 2 * math.sin(k / 3)
        return p, p + 0.4, p - 0.4, p + 0.05
    c15 = sessions_15m(DAYS, fn, last_day_bars=10)
    c5 = history_5m(5)
    wild = frame(at(9, 15), [(100, 106, 94, 100 + (3 if i % 2 else -3), 1000) for i in range(6)])
    assert classify(c15, pd.concat([c5, wild])) == Regime.HIGH_VOL
    assert classify(c15, c5) == Regime.RANGE


def test_not_enough_history_is_range():
    assert classify(sessions_15m([TODAY], trend(1), last_day_bars=10)) == Regime.RANGE


def test_index_zero_volume_ok():
    assert classify(sessions_15m(DAYS, trend(1), volume=0.0, last_day_bars=10)) == Regime.TREND_UP
