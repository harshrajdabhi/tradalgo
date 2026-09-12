from datetime import date, datetime

import pytest

from tradalgo.clock import IST
from tradalgo.risk.limits import (
    DailyRiskState, check_limits, kill_switch_active, register_entry, register_exit,
)
from tradalgo.strategies.base import Regime, Signal

TS = datetime(2026, 9, 11, 10, 0, tzinfo=IST)


def sig(symbol="SBIN", strategy="orb"):
    return Signal(symbol, strategy, "long", TS, 100.0, 98.0, Regime.TREND_UP, Regime.TREND_UP, False, "t")


def state_after(first=("SBIN", "orb"), net_r=None):
    s = register_entry(DailyRiskState(date(2026, 9, 11)), sig(*first))
    return s if net_r is None else register_exit(s, first[0], net_r)


def test_register_is_pure():
    s0 = DailyRiskState(date(2026, 9, 11))
    s1 = register_entry(s0, sig())
    assert s0.trades_taken == 0 and s0.taken == [] and s0.open_trade_symbols == []
    assert s1.trades_taken == 1 and s1.open_trade_symbols == ["SBIN"]
    s2 = register_exit(s1, "SBIN", -1.2)
    assert s1.realized_r == 0 and s1.taken[0][2] is False
    assert s2.realized_r == -1.2 and s2.open_trade_symbols == [] and s2.taken == [("SBIN", "orb", True, -1.2)]


@pytest.mark.parametrize(
    "state, signal, expected",
    [
        (DailyRiskState(date(2026, 9, 11)), sig(), None),
        (state_after(), sig("INFY", "vwap"), None),                       # independent while first open
        (state_after(), sig("SBIN", "vwap"), "same symbol"),               # same symbol, open
        (state_after(net_r=2.0), sig("SBIN", "vwap"), "same symbol"),      # same symbol, closed
        (state_after(net_r=2.0), sig("SBIN", "orb"), "same symbol"),       # same strategy+symbol
        (state_after(net_r=0.5), sig("INFY", "orb"), None),                # small loss/win: other symbol ok
        (state_after(net_r=-1.0), sig("INFY", "orb"), "different strategy"),
        (state_after(net_r=-1.0), sig("INFY", "vwap"), None),
        (DailyRiskState(date(2026, 9, 11), realized_r=-2.0), sig(), "daily loss limit"),
        (DailyRiskState(date(2026, 9, 11), trades_taken=2), sig("TCS", "gap"), "max trades"),
    ],
)
def test_check_limits(state, signal, expected):
    result = check_limits(state, signal, max_trades_per_day=2, daily_loss_limit_r=2.0)
    if expected is None:
        assert result is None
    else:
        assert expected in result


def test_two_trade_cap_after_two_entries():
    s = register_entry(state_after(net_r=1.0), sig("INFY", "vwap"))
    assert "max trades" in check_limits(s, sig("TCS", "gap"), 2, 2.0)


def test_cumulative_loss_limit():
    s = register_exit(register_entry(state_after(net_r=-0.5), sig("INFY", "vwap")), "INFY", -1.5)
    assert "daily loss limit" in check_limits(s, sig("TCS", "gap"), 3, 2.0)


def test_kill_switch(tmp_path):
    assert not kill_switch_active(tmp_path)
    (tmp_path / "KILL").touch()
    assert kill_switch_active(tmp_path)
