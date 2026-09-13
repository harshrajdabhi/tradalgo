from datetime import date, datetime, timedelta

import pytest

from tradalgo.clock import IST
from tradalgo.config import CapitalConfig
from tradalgo.risk.costs import estimate_round_trip
from tradalgo.config import CostsConfig
from tradalgo.risk.limits import DailyRiskState
from tradalgo.risk.plan import Rejection, TradePlan
from tradalgo.risk.validator import validate
from tradalgo.strategies.base import Regime, Signal

TS = datetime(2026, 9, 11, 10, 0, tzinfo=IST)
CFG = CapitalConfig(initial_capital=20000, max_risk_pct=0.03, max_leverage=5, fallback_leverage=3,
                    fixed_cost_rupees=50, max_trades_per_day=2, daily_loss_limit_r=2)


def sig(direction="long", entry=100.0, stop=98.0, symbol="SBIN", strategy="orb"):
    return Signal(symbol, strategy, direction, TS, entry, stop, Regime.TREND_UP, Regime.TREND_UP, False, "t")


def run(signal, capital=20000.0, symbol_leverage=None, levels=(), state=None, **kw):
    kw.setdefault("costs_cfg", CostsConfig())
    return validate(signal, capital=capital, capital_cfg=CFG, symbol_leverage=symbol_leverage,
                    levels=list(levels), limits_state=state or DailyRiskState(date(2026, 9, 11)), **kw)


def test_accepted_long_exact_numbers():
    p = run(sig(), symbol_leverage=None, levels=[105.0, 97.0, 91.0])
    assert isinstance(p, TradePlan)
    assert p.qty == 272 and p.leverage_used == 3.0             # floor(600 / (100.2 - 98))
    assert p.margin_required == pytest.approx(272 * 100.2 / 3)
    assert p.risk_rupees == pytest.approx(272 * 2.2)
    assert p.risk_rupees <= 600.0
    assert (p.target_2r, p.target_3r) == (104.0, 106.0)
    assert p.est_cost == pytest.approx(estimate_round_trip(100.2, 272, "long", CostsConfig()))
    assert p.est_cost == pytest.approx(2 * 8.1763 + 0.0000297 * 54508.8 + 54508.8 * 1e-6 + 0.0002 * 27254.4
                                       + 0.00003 * 27254.4 + 0.18 * (2 * 8.1763 + 0.0000297 * 54508.8 + 54508.8 * 1e-6),
                                       rel=1e-4)
    assert p.room_to_level_r == pytest.approx(2.4)             # (105 - 100.2) / 2
    assert p.expected_value_r == pytest.approx(0.4 * 2.0 - 0.6 - p.est_cost / (272 * 2))
    assert (p.limit_low, p.limit_high) == pytest.approx((100.0, 100.2))
    assert p.valid_until == TS + timedelta(minutes=10)


def test_accepted_short_exact_numbers():
    p = run(sig("short", 200.0, 204.0), symbol_leverage=2.0, levels=[210.0, 190.0, 180.0])
    assert isinstance(p, TradePlan)
    assert p.qty == 136 and p.leverage_used == 2.0             # floor(600 / (204 - 199.6))
    assert p.margin_required == pytest.approx(136 * 199.6 / 2)
    assert p.risk_rupees == pytest.approx(136 * 4.4) and p.risk_rupees <= 600.0
    assert (p.target_2r, p.target_3r) == (192.0, 188.0)
    assert p.room_to_level_r == pytest.approx(2.4)
    assert (p.limit_low, p.limit_high) == pytest.approx((199.6, 200.0))


def test_no_opposing_level_is_finite():
    p = run(sig(), levels=[90.0])
    assert isinstance(p, TradePlan) and p.room_to_level_r == 99.0


@pytest.mark.parametrize(
    "kwargs, reason",
    [
        (dict(signal=sig(), state=DailyRiskState(date(2026, 9, 11), trades_taken=2)), "max trades"),
        (dict(signal=sig(), state=DailyRiskState(date(2026, 9, 11), realized_r=-2.0)), "daily loss limit"),
        (dict(signal=sig(entry=100.0, stop=50.0), capital=1000.0), "qty"),
        (dict(signal=sig(), levels=[103.0]), "room"),
        (dict(signal=sig(), levels=[100.0]), "room"),                   # level exactly at entry
        (dict(signal=sig(), levels=[104.1]), "room"),                   # 2.05R from entry, 1.95R from band edge
        (dict(signal=sig(), state=DailyRiskState(date(2026, 9, 10))), "stale"),
        (dict(signal=sig("short", 200.0, 204.0), levels=[195.0]), "room"),
        (dict(signal=sig(), win_prob=0.3), "expected value"),
        (dict(signal=sig(entry=100.0, stop=99.0), capital=1000.0,  # 30 qty, 1% brokerage -> cost_r ~2
              costs_cfg=CostsConfig(brokerage_pct_per_order=0.01, brokerage_cap_per_order=100)), "expected value"),
    ],
)
def test_rejections(kwargs, reason):
    signal = kwargs.pop("signal")
    r = run(signal, **kwargs)
    assert isinstance(r, Rejection) and r.signal is signal
    assert reason in r.reason


def test_band_fill_risk_never_exceeds_cap():
    for entry, stop, direction in [(100.0, 98.0, "long"), (100.0, 99.0, "long"), (200.0, 204.0, "short")]:
        p = run(sig(direction, entry, stop))
        assert isinstance(p, TradePlan)
        for fill in (p.limit_low, p.limit_high):
            assert p.qty * abs(fill - stop) <= 20000 * 0.03 + 1e-9


def test_real_charges_on_small_trade_are_a_small_cost_r():
    p = run(sig(entry=100.0, stop=99.0), capital=1000.0)
    assert isinstance(p, TradePlan) and p.est_cost / (p.qty * 1.0) < 0.2


def test_ev_uses_partial_and_runner_weights():
    p = run(sig(), runner_avg_r=3.0, partial_fraction=0.5)
    assert p.expected_value_r == pytest.approx(0.4 * (0.5 * 2 + 0.5 * 3.0) - 0.6 - p.est_cost / (272 * 2))
