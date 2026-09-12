import json
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy import insert

from tradalgo.dashboard import queries
from tradalgo.storage.db import init_db, make_engine
from tradalgo.storage.schema import (
    alerts, backtest_runs, backtest_trades, decisions, health_events, job_runs,
    paper_trades, shortlist, signals, user_actions,
)

NOW = "2026-09-10T09:30:00+05:30"


def seed(engine):
    with engine.begin() as conn:
        conn.execute(insert(shortlist).values(
            trade_date="2026-09-10", rank=1, symbol="RELIANCE", composite_score=0.8,
            factor_scores_json="{}", reasons="strong", gap_pct=1.2, demoted=0,
        ))
        sig_id = conn.execute(insert(signals).values(
            ts=NOW, symbol="RELIANCE", strategy="orb", direction="long", regime="trend",
            market_regime="trend", entry=100.0, stop_loss=98.0, target_2r=104.0, target_3r=106.0,
            features_json="{}", mode="live",
        )).inserted_primary_key[0]
        conn.execute(insert(decisions).values(
            signal_id=sig_id, accepted=1, qty=10, leverage_used=2.0, risk_rupees=200.0,
            est_cost=50.0, expected_value_r=0.5, room_to_target_r=3.0,
        ))
        alert_id = conn.execute(insert(alerts).values(
            dedup_key="d1", alert_type="entry", symbol="RELIANCE", signal_id=sig_id, text="go",
            status="failed", created_at=NOW, attempts=1, last_error="timeout",
        )).inserted_primary_key[0]
        conn.execute(insert(user_actions).values(alert_id=alert_id, action="taken", price=100.0, ts=NOW))
        conn.execute(insert(paper_trades).values(
            signal_id=sig_id, taken_by_user=1, entry_ts=NOW, entry_price=100.0, qty=10,
            exit_ts=NOW, exit_price=104.0, exit_reason="target", mfe_r=2.5, mae_r=-0.3,
            slippage_rupees=5.0, gross_r=2.0, net_r=1.9,
        ))
        run_id = conn.execute(insert(backtest_runs).values(
            created_at=NOW, status="done", params_json=json.dumps({"from": "2026-01-01"}),
            progress_pct=100, metrics_json=json.dumps({"trades": 1, "win_rate": 1.0, "expectancy_r": 1.9,
                                                        "max_drawdown_r": 0.0, "by_strategy": {"orb": {"trades": 1}}}),
        )).inserted_primary_key[0]
        conn.execute(insert(backtest_trades).values(
            backtest_run_id=run_id, signal_id=sig_id, trade_date="2026-09-10", symbol="RELIANCE",
            strategy="orb", direction="long", entry_ts=NOW, entry_price=100.0, exit_ts=NOW,
            exit_price=104.0, exit_reason="target", qty=10, mfe_r=2.5, mae_r=-0.3, gross_r=2.0, net_r=1.9,
        ))
        conn.execute(insert(job_runs).values(
            job="screen", run_date="2026-09-10", started_at=NOW, finished_at=NOW, status="succeeded",
        ))
        conn.execute(insert(health_events).values(
            ts=NOW, component="data", level="warning", message="fallback used",
        ))
    return run_id


def _tmp_db_path() -> Path:
    return Path(tempfile.gettempdir()) / f"tradalgo_test_{uuid.uuid4().hex}.db"


def make_seeded_engine():
    engine = make_engine(_tmp_db_path())
    init_db(engine)
    seed(engine)
    return engine


def make_empty_engine():
    engine = make_engine(_tmp_db_path())
    init_db(engine)
    return engine


def test_shortlist_for_date_empty():
    engine = make_empty_engine()
    df = queries.shortlist_for_date(engine, "2026-09-10")
    assert df.empty


def test_shortlist_for_date_seeded():
    engine = make_seeded_engine()
    df = queries.shortlist_for_date(engine, "2026-09-10")
    assert len(df) == 1
    assert df.iloc[0]["symbol"] == "RELIANCE"


def test_signals_with_decisions():
    engine = make_seeded_engine()
    df = queries.signals_with_decisions(engine, "2026-09-10")
    assert len(df) == 1
    assert df.iloc[0]["accepted"] == 1


def test_trade_positions():
    engine = make_seeded_engine()
    df = queries.trade_positions(engine)
    assert len(df) == 1
    assert df.iloc[0]["net_r"] == 1.9
    assert df.iloc[0]["user_action"] == "taken"


def test_alerts_log_filters():
    engine = make_seeded_engine()
    df = queries.alerts_log(engine, status="failed")
    assert len(df) == 1
    assert queries.alerts_log(engine, status="sent").empty


def test_backtest_runs_and_metrics():
    engine = make_seeded_engine()
    runs = queries.backtest_runs_list(engine)
    assert len(runs) == 1
    run_id = int(runs.iloc[0]["id"])
    metrics = queries.backtest_run_metrics(engine, run_id)
    assert metrics["trades"] == 1
    trades = queries.backtest_run_trades(engine, run_id)
    assert len(trades) == 1


def test_backtest_metrics_empty_run():
    engine = make_empty_engine()
    assert queries.backtest_run_metrics(engine, 999) == {}


def test_journal():
    engine = make_seeded_engine()
    df = queries.journal(engine, date_from="2026-09-01", date_to="2026-09-30")
    assert len(df) == 1
    assert queries.journal(engine, strategy="gap").empty


def test_expectancy_by_strategy():
    engine = make_seeded_engine()
    df = queries.expectancy_by(engine, "strategy")
    assert len(df) == 1
    assert df.iloc[0]["grp"] == "orb"
    assert df.iloc[0]["trades"] == 1


def test_mfe_mae_points():
    engine = make_seeded_engine()
    df = queries.mfe_mae_points(engine)
    assert len(df) == 1


def test_live_vs_backtest_expectancy():
    engine = make_seeded_engine()
    df = queries.live_vs_backtest_expectancy(engine)
    assert len(df) == 1
    assert df.iloc[0]["live_trades"] == 1
    assert df.iloc[0]["backtest_trades"] == 1


def test_latest_job_runs():
    engine = make_seeded_engine()
    df = queries.latest_job_runs(engine)
    assert len(df) == 1
    assert df.iloc[0]["job"] == "screen"


def test_health_events_and_degraded():
    engine = make_seeded_engine()
    assert len(queries.health_events(engine)) == 1
    assert len(queries.degraded_periods(engine, "data")) == 1
    assert queries.degraded_periods(engine, "socket").empty
