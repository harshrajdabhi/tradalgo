import math

import pandas as pd
import pytest

from tests.strategy_fixtures import TODAY, at, frame, history_5m, prior_days, resample_15m, sessions_15m
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


def u_session(day, scale=1.0, gap=0.0):
    rows = []
    for i in range(75):
        half = scale * (1.0 if i < 4 or i > 70 else 0.5)
        p = 100.0 + gap
        rows.append((p, p + half, p - half, p + (0.05 if i % 2 else -0.05), 1000))
    return frame(at(9, 15, day), rows)


def u_history(today_scale):
    days = prior_days(12)
    parts = [u_session(d, gap=0.5 if j % 2 else -0.5) for j, d in enumerate(days)]
    return pd.concat(parts + [u_session(TODAY, scale=today_scale, gap=0.5)])


@pytest.mark.parametrize("hh, mm", [(9, 30), (9, 35), (9, 45), (10, 0)])
def test_normal_open_volatility_is_not_high_vol(hh, mm):
    c5 = u_history(1.0)
    c5 = c5[c5.index + pd.Timedelta(minutes=5) <= at(hh, mm)]
    c15 = resample_15m(c5)
    assert classify(c15, c5) != Regime.HIGH_VOL


def test_abnormal_session_is_high_vol():
    c5 = u_history(3.0)
    c5 = c5[c5.index + pd.Timedelta(minutes=5) <= at(10, 0)]
    assert classify(resample_15m(c5), c5) == Regime.HIGH_VOL


def test_not_enough_history_is_range():
    assert classify(sessions_15m([TODAY], trend(1), last_day_bars=10)) == Regime.RANGE


def test_index_zero_volume_ok():
    assert classify(sessions_15m(DAYS, trend(1), volume=0.0, last_day_bars=10)) == Regime.TREND_UP
