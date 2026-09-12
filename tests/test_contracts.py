from datetime import datetime

import pytest

from tradalgo.clock import IST
from tradalgo.strategies.base import Regime, Signal

TS = datetime(2026, 9, 11, 9, 35, tzinfo=IST)


def make(direction="long", entry=100.0, stop=98.0, ts=TS):
    return Signal("SBIN", "orb", direction, ts, entry, stop, Regime.TREND_UP, Regime.TREND_UP, False, "test")


def test_long_targets_and_risk():
    s = make()
    assert s.risk_per_share == 2.0
    assert s.target(2) == 104.0 and s.target(3) == 106.0


def test_short_targets():
    assert make("short", entry=100.0, stop=101.5).target(2) == 97.0


@pytest.mark.parametrize("direction, stop", [("long", 100.0), ("long", 101.0), ("short", 99.0)])
def test_stop_on_wrong_side_rejected(direction, stop):
    with pytest.raises(ValueError, match="wrong side"):
        make(direction, entry=100.0, stop=stop)


def test_naive_ts_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        make(ts=datetime(2026, 9, 11, 9, 35))
