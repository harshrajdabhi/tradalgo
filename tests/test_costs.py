import subprocess
from pathlib import Path

import pytest

from tradalgo.config import CostsConfig
from tradalgo.risk.costs import estimate_round_trip, intraday_charges, order_brokerage

CFG = CostsConfig()
ROOT = Path(__file__).resolve().parents[1]


def test_order_brokerage_below_and_at_cap():
    assert order_brokerage(3000, CFG) == pytest.approx(0.9)       # 0.03% below cap
    assert order_brokerage(600000, CFG) == 20.0                   # 180 capped to 20


def test_small_trade_long():
    # 10 @ 300 both legs: brokerage 0.9+0.9, exch 6000*0.0000297, sebi 0.006, stt 0.6, stamp 0.09, gst on brok+exch+sebi
    expected = 1.8 + 0.1782 + 0.006 + 0.6 + 0.09 + 0.18 * (1.8 + 0.1782 + 0.006)
    assert intraday_charges([3000], [3000], CFG) == pytest.approx(expected)
    assert estimate_round_trip(300, 10, "long", CFG) == pytest.approx(expected)
    assert expected == pytest.approx(3.031356)


def test_large_trade_long_hits_brokerage_cap():
    expected = 40 + 35.64 + 1.2 + 120 + 18 + 0.18 * (40 + 35.64 + 1.2)
    assert estimate_round_trip(2000, 300, "long", CFG) == pytest.approx(expected)
    assert expected == pytest.approx(228.6712)


def test_large_trade_short_swaps_buy_and_sell():
    # short 300 @ 2000 covered at 1990: sell 600000 (STT), buy 597000 (stamp)
    t = 1197000
    expected = 40 + t * 0.0000297 + t * 10 / 1e7 + 120 + 597000 * 0.00003 + 0.18 * (40 + t * 0.0000297 + t * 10 / 1e7)
    assert estimate_round_trip(2000, 300, "short", CFG, target_price=1990) == pytest.approx(expected)
    assert intraday_charges([597000], [600000], CFG) == pytest.approx(expected)
    assert estimate_round_trip(2000, 300, "long", CFG, target_price=1990) != pytest.approx(expected)


def test_brokerage_is_per_order_value_not_an_even_split():
    # buy ₹100k (capped 20), partial sell ₹61.2k (18.36) and final sell ₹40.8k (12.24)
    brokerage = 20 + 18.36 + 12.24
    t = 202000
    expected = brokerage + t * 0.0000297 + t * 10 / 1e7 + 102000 * 0.0002 + 100000 * 0.00003 \
        + 0.18 * (brokerage + t * 0.0000297 + t * 10 / 1e7)
    assert intraday_charges([100000], [61200, 40800], CFG) == pytest.approx(expected)
    assert intraday_charges([100000], [61200, 40800], CFG) == pytest.approx(90.425652)


def test_partial_exit_capped_orders():
    expected = 60 + 35.64 + 1.2 + 120 + 18 + 0.18 * (60 + 35.64 + 1.2)
    assert intraday_charges([600000], [360000, 240000], CFG) == pytest.approx(expected)


def test_costs_config_rejects_negative():
    with pytest.raises(ValueError):
        CostsConfig(stt_sell_pct=-0.1)


def test_fixed_cost_rupees_no_longer_read():
    out = subprocess.run(["grep", "-rln", "fixed_cost_rupees", "--include=*.py", str(ROOT / "tradalgo")],
                         capture_output=True, text=True).stdout.split()
    assert [Path(p).name for p in out] == ["config.py"]
