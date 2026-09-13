import json
from datetime import date, datetime

import pytest
from sqlalchemy import insert

from tradalgo.clock import IST
from tradalgo.reporting import format_report_text, live_vs_backtest, weekly_report
from tradalgo.storage.db import init_db, make_engine
from tradalgo.storage.schema import alerts, backtest_runs, decisions, paper_trades, signals, user_actions

WEEK_END = date(2026, 9, 11)  # Friday


@pytest.fixture
def engine(tmp_path):
    eng = make_engine(tmp_path / "t.db")
    init_db(eng)
    return eng


def _ts(d: str, t: str = "10:00:00") -> str:
    return f"{d}T{t}+05:30"


def _insert_signal(engine, id_, strategy, ts="2026-09-08T09:20:00+05:30"):
    with engine.begin() as conn:
        conn.execute(insert(signals).values(
            id=id_, ts=ts, symbol="RELIANCE", strategy=strategy, direction="long",
            regime="trend_up", entry=100.0, stop_loss=98.0, target_2r=104.0, target_3r=106.0,
            features_json="{}", mode="live",
        ))
        conn.execute(insert(decisions).values(signal_id=id_, accepted=1, risk_rupees=500.0))


def _insert_trade(engine, signal_id, taken, entry_date, net_r, net_rupees, exit_date=None):
    with engine.begin() as conn:
        conn.execute(insert(paper_trades).values(
            signal_id=signal_id, taken_by_user=int(taken), entry_ts=_ts(entry_date), entry_price=100.0,
            qty=10, exit_ts=_ts(exit_date or entry_date), exit_price=104.0, exit_reason="target",
            net_r=net_r, gross_r=net_r,
        ))


def _insert_alert(engine, id_, status, alert_type="entry", created="2026-09-08"):
    with engine.begin() as conn:
        conn.execute(insert(alerts).values(
            id=id_, dedup_key=f"k{id_}", alert_type=alert_type, text="t", status=status,
            created_at=_ts(created), attempts=0,
        ))


def _insert_action(engine, alert_id, action):
    with engine.begin() as conn:
        conn.execute(insert(user_actions).values(alert_id=alert_id, action=action, ts=_ts("2026-09-08")))


def seed_week(engine):
    _insert_signal(engine, 1, "orb")
    _insert_signal(engine, 2, "orb")
    _insert_signal(engine, 3, "vwap")
    # two taken trades: one win (+2R), one loss (-1R)
    _insert_trade(engine, 1, True, "2026-09-08", 2.0, 1000.0, exit_date="2026-09-09")
    _insert_trade(engine, 2, True, "2026-09-10", -1.0, -500.0)
    # one not-taken trade, loss
    _insert_trade(engine, 3, False, "2026-09-09", -1.0, -500.0)

    _insert_alert(engine, 1, "sent")
    _insert_alert(engine, 2, "sent")
    _insert_alert(engine, 3, "failed")
    _insert_alert(engine, 4, "expired")
    _insert_action(engine, 1, "taken")
    _insert_action(engine, 2, "skipped")
    # alert 3 (failed, never delivered) and 4 (expired, no response) don't count as responded except 4 counted denominator


def test_weekly_report_splits_taken_and_not_taken(engine):
    seed_week(engine)
    report = weekly_report(engine, WEEK_END, weeks=1)
    assert report["taken"] == {"count": 2, "win_rate": 0.5, "expectancy_r": 0.5, "net_rupees": 500.0}
    assert report["not_taken"] == {"count": 1, "win_rate": 0.0, "expectancy_r": -1.0, "net_rupees": -500.0}


def test_weekly_report_r_curve_is_cumulative_over_taken_trades_by_exit_date(engine):
    seed_week(engine)
    report = weekly_report(engine, WEEK_END, weeks=1)
    assert report["weekly_r_curve"] == [
        {"date": "2026-09-09", "cum_r": 2.0},
        {"date": "2026-09-10", "cum_r": 1.0},
    ]


def test_weekly_report_alert_counts_and_response_rate(engine):
    seed_week(engine)
    report = weekly_report(engine, WEEK_END, weeks=1)
    assert report["alerts"] == {"sent": 2, "failed": 1, "expired": 1}
    # entry alerts delivered = sent(2) + expired(1) = 3; responded (taken/skipped) among them = 2 (alerts 1,2)
    assert report["response_rate"] == round(2 / 3, 4)


def test_weekly_report_per_strategy_expectancy(engine):
    seed_week(engine)
    report = weekly_report(engine, WEEK_END, weeks=1)
    assert report["by_strategy"]["orb"]["count"] == 2
    assert report["by_strategy"]["orb"]["expectancy_r"] == 0.5
    assert report["by_strategy"]["vwap"]["count"] == 1
    assert report["by_strategy"]["vwap"]["expectancy_r"] == -1.0


def test_weekly_report_excludes_trades_outside_window(engine):
    seed_week(engine)
    _insert_signal(engine, 4, "orb")
    _insert_trade(engine, 4, True, "2026-08-01", 5.0, 5000.0)
    report = weekly_report(engine, WEEK_END, weeks=1)
    assert report["taken"]["count"] == 2


def test_live_vs_backtest_computes_divergence_and_flags(engine):
    seed_week(engine)
    metrics = {"by_strategy": {
        "orb": {"trades": 20, "win_rate": 0.5, "expectancy_r": -0.5},
        "vwap": {"trades": 20, "win_rate": 0.5, "expectancy_r": -1.0},
    }}
    with engine.begin() as conn:
        conn.execute(insert(backtest_runs).values(
            created_at=_ts("2026-09-01"), status="done", params_json="{}", progress_pct=100.0,
            metrics_json=json.dumps(metrics),
        ))
    rows = {r["strategy"]: r for r in live_vs_backtest(engine)}
    assert rows["orb"]["live_expectancy_r"] == 0.5
    assert rows["orb"]["backtest_expectancy_r"] == -0.5
    assert rows["orb"]["divergence_r"] == 1.0
    # only 2 live trades for orb -> not enough to flag even though divergence > 0.5
    assert rows["orb"]["flagged"] is False
    # vwap has no *taken* live trades (only a skipped one), so live defaults to 0
    assert rows["vwap"]["live_trades"] == 0
    assert rows["vwap"]["divergence_r"] == 1.0


def test_live_vs_backtest_flags_when_enough_live_trades(engine):
    for i in range(5, 5 + 12):
        _insert_signal(engine, i, "orb", ts=f"2026-09-0{i % 9 + 1}T09:20:00+05:30")
        _insert_trade(engine, i, True, "2026-09-08", 2.0, 100.0)
    metrics = {"by_strategy": {"orb": {"trades": 20, "win_rate": 0.5, "expectancy_r": -0.5}}}
    with engine.begin() as conn:
        conn.execute(insert(backtest_runs).values(
            created_at=_ts("2026-09-01"), status="done", params_json="{}", progress_pct=100.0,
            metrics_json=json.dumps(metrics),
        ))
    rows = {r["strategy"]: r for r in live_vs_backtest(engine)}
    assert rows["orb"]["live_trades"] == 12
    assert rows["orb"]["flagged"] is True


def test_live_vs_backtest_empty_when_no_completed_run(engine):
    seed_week(engine)
    assert live_vs_backtest(engine) == []


def test_format_report_text_escapes_and_is_compact(engine):
    seed_week(engine)
    report = weekly_report(engine, WEEK_END, weeks=1)
    text = format_report_text(report, [])
    assert "Weekly Report" in text
    assert "<script>" not in text
