import json

import pytest

from tradalgo.backtest.metrics import compute_metrics

KEYS = {"trades", "win_rate", "expectancy_r", "expectancy_r_no_slippage", "profit_factor", "max_drawdown_r",
        "net_r", "net_rupees", "by_strategy", "by_regime"}


def _t(net_r, no_slip, rupees, strategy, regime):
    return {"net_r": net_r, "net_r_no_slippage": no_slip, "net_rupees": rupees, "strategy": strategy,
            "regime": regime}


def test_exact_numbers_on_hand_made_trades():
    trades = [
        _t(2.0, 2.1, 1200.0, "orb", "trend_up"),
        _t(-1.0, -0.9, -600.0, "orb", "range"),
        _t(0.5, 0.6, 300.0, "vwap", "trend_up"),
        _t(-1.0, -0.9, -600.0, "vwap", "trend_up"),
    ]
    m = compute_metrics(trades)
    assert set(m) == KEYS
    assert m["trades"] == 4
    assert m["win_rate"] == pytest.approx(0.5)
    assert m["expectancy_r"] == pytest.approx(0.125)
    assert m["expectancy_r_no_slippage"] == pytest.approx(0.225)
    assert m["profit_factor"] == pytest.approx(1.25)
    assert m["max_drawdown_r"] == pytest.approx(1.5)  # cum 2, 1, 1.5, 0.5
    assert m["net_r"] == pytest.approx(0.5)
    assert m["net_rupees"] == pytest.approx(300.0)
    assert m["by_strategy"]["orb"] == {"trades": 2, "win_rate": 0.5, "expectancy_r": 0.5}
    assert m["by_strategy"]["vwap"] == {"trades": 2, "win_rate": 0.5, "expectancy_r": -0.25}
    assert m["by_regime"]["trend_up"]["trades"] == 3
    assert m["by_regime"]["range"] == {"trades": 1, "win_rate": 0.0, "expectancy_r": -1.0}


def test_no_losses_profit_factor_is_none():
    assert compute_metrics([_t(1.0, 1.0, 10.0, "orb", "range")])["profit_factor"] is None


def test_zero_trades_is_valid_json():
    m = compute_metrics([])
    assert set(m) == KEYS
    assert m["trades"] == 0 and m["expectancy_r"] == 0.0 and m["by_strategy"] == {}
    json.loads(json.dumps(m, allow_nan=False))
