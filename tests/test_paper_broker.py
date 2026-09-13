import pytest

from tradalgo.backtest.paper_broker import PaperBroker
from tradalgo.config import CostsConfig
from tradalgo.risk.costs import intraday_charges
from tradalgo.engine.positions import PositionManager
from tests.backtest_fixtures import at, make_plan, make_signal

COSTS = CostsConfig()
FREE = CostsConfig(brokerage_pct_per_order=0, stt_sell_pct=0, exchange_txn_pct=0, sebi_per_crore=0,
                   stamp_buy_pct=0, gst_pct=0)


@pytest.fixture
def plan():
    return make_plan(make_signal(entry=100.0, stop=99.0), qty=100)  # band [100, 100.1]


def test_fill_inside_band_at_next_open(plan):
    assert PaperBroker.fill_price(plan, 100.05) == 100.05
    assert PaperBroker.fill_price(plan, 100.0) == 100.0


def test_missed_when_next_open_outside_band(plan):
    assert PaperBroker.fill_price(plan, 100.2) is None
    assert PaperBroker.fill_price(plan, 99.9) is None


def _stop_exit(broker, plan, stop_price):
    tid = broker.open(plan, signal_id=7, entry_ts=at(9, 40), fill=100.05)
    pm = PositionManager()
    pm.open(tid, plan, 100.05)
    rec = None
    for ev in pm.on_price(at(9, 50), high=100.1, low=97.0, close=97.5, bar_closed=True, open=stop_price):
        rec = broker.on_event(ev) or rec
    return rec


def test_slippage_and_modeled_charges_arithmetic(plan):
    broker = PaperBroker(slippage_pct=0.1, costs=COSTS)
    rec = _stop_exit(broker, plan, stop_price=100.0)
    assert rec["exit_reason"] == "stop_hit"
    assert rec["gross_r"] == pytest.approx(-1.05)            # (99 - 100.05) * 100 / (100 * 1)
    raw_charges = intraday_charges(100.05 * 100, 99 * 100, COSTS)
    assert rec["net_r_no_slippage"] == pytest.approx(-1.05 - raw_charges / 100)
    # entry 100.05 * 1.001 = 100.15005; exit 99 * 0.999 = 98.901
    assert rec["entry_price"] == pytest.approx(100.15005)
    assert rec["exit_price"] == pytest.approx(98.901)
    charges = intraday_charges(100.15005 * 100, 98.901 * 100, COSTS)
    assert charges == pytest.approx(10.047, abs=0.01)
    assert rec["net_rupees"] == pytest.approx(-124.905 - charges)
    assert rec["net_r"] == pytest.approx((-124.905 - charges) / 100)
    assert rec["signal_id"] == 7 and rec["qty"] == 100


def test_gap_through_stop_fills_at_worse_open(plan):
    broker = PaperBroker(slippage_pct=0.0, costs=FREE)
    rec = _stop_exit(broker, plan, stop_price=98.0)
    assert rec["exit_price"] == pytest.approx(98.0)
    assert rec["gross_r"] == pytest.approx(-2.05)


def test_partial_and_runner_legs(plan):
    broker = PaperBroker(slippage_pct=0.0, costs=COSTS)
    tid = broker.open(plan, signal_id=1, entry_ts=at(9, 40), fill=100.0)
    pm = PositionManager()
    pm.open(tid, plan, 100.0)
    rec = None
    for ev in pm.on_price(at(9, 45), high=102.2, low=99.9, close=102.0, bar_closed=True, open=100.0):
        rec = broker.on_event(ev) or rec
    assert rec is None
    for ev in pm.on_price(at(9, 50), high=103.5, low=101.5, close=103.0, bar_closed=True, open=102.0):
        rec = broker.on_event(ev) or rec
    assert [leg["kind"] for leg in rec["legs"]] == ["partial_exit", "runner_exit"]
    assert rec["gross_r"] == pytest.approx(0.6 * 2 + 0.4 * 3)
    charges = intraday_charges(100.0 * 100, 102.0 * 60 + 103.0 * 40, COSTS, orders=3)
    assert rec["net_r"] == pytest.approx(2.4 - charges / 100)


def test_mfe_mae_tracked_while_open(plan):
    broker = PaperBroker(slippage_pct=0.0, costs=FREE)
    tid = broker.open(plan, signal_id=1, entry_ts=at(9, 40), fill=100.0)
    broker.on_bar(tid, at(9, 35), high=110.0, low=90.0)  # before entry: ignored
    broker.on_bar(tid, at(9, 40), high=101.5, low=99.4)
    broker.on_bar(tid, at(9, 45), high=100.8, low=99.7)
    rec = broker.force_close(tid, at(9, 50), 100.0, "eod_no_data")
    assert rec["mfe_r"] == pytest.approx(1.5)
    assert rec["mae_r"] == pytest.approx(-0.6)
    assert rec["exit_reason"] == "eod_no_data"
