import pytest

from tradalgo.risk.sizing import effective_leverage, margin_required, position_qty


@pytest.mark.parametrize("sym, expected", [(None, 3.0), (2.0, 2.0), (8.0, 5.0), (5.0, 5.0)])
def test_effective_leverage(sym, expected):
    assert effective_leverage(sym, 5.0, 3.0) == expected


@pytest.mark.parametrize(
    "entry, stop, capital, lev, expected",
    [
        (100.0, 98.0, 20000, 5, 300),     # risk-bound: 600/2
        (100.0, 99.9, 20000, 5, 1000),    # leverage-bound: 100000/100
        (100.0, 99.9, 20000, 1, 200),
        (5000.0, 4990.0, 20000, 1, 4),
        (100.0, 50.0, 1000, 5, 0),        # 30/50 floors to 0
        (30000.0, 29990.0, 20000, 1, 0),  # can't afford one share
    ],
)
def test_position_qty(entry, stop, capital, lev, expected):
    assert position_qty(entry, stop, capital, 0.03, lev) == expected


def test_leverage_never_increases_rupee_risk():
    for lev in [1, 2, 3, 4, 5]:
        for stop in [99.99, 99.5, 98, 90]:
            qty = position_qty(100.0, stop, 20000, 0.03, lev)
            assert qty * abs(100.0 - stop) <= 20000 * 0.03 + 1e-9


def test_margin_required():
    assert margin_required(300, 100.0, 5) == 6000.0
