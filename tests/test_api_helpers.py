"""Shared tmp-config + seeded-DB fixture for tests/test_api_*.py, reusing the seed helper from
tests/test_dashboard_queries.py (copied here per the B1 brief since dashboard/ is deleted at B4).
"""
import json
import shutil
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

import yaml
from sqlalchemy import insert

from tradalgo.clock import IST
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
        trade_id = conn.execute(insert(backtest_trades).values(
            backtest_run_id=run_id, signal_id=sig_id, trade_date="2026-09-10", symbol="RELIANCE",
            strategy="orb", direction="long", entry_ts=NOW, entry_price=100.0, exit_ts=NOW,
            exit_price=104.0, exit_reason="target", qty=10, mfe_r=2.5, mae_r=-0.3, gross_r=2.0, net_r=1.9,
        )).inserted_primary_key[0]
        conn.execute(insert(job_runs).values(
            job="screen", run_date="2026-09-10", started_at=NOW, finished_at=NOW, status="succeeded",
        ))
        conn.execute(insert(health_events).values(
            ts=NOW, component="data", level="warning", message="fallback used",
        ))
    return {"run_id": run_id, "trade_id": trade_id, "signal_id": sig_id, "alert_id": alert_id}


def _tmp_db_path() -> Path:
    return Path(tempfile.gettempdir()) / f"tradalgo_api_test_{uuid.uuid4().hex}.db"


def make_config(tmp_path: Path, db_path: Path | None = None) -> Path:
    """A valid config.yaml pointed at a tmp data dir, based on the repo's own config.yaml."""
    with open("config.yaml") as f:
        cfg = yaml.safe_load(f)
    unique = uuid.uuid4().hex
    data_dir = tmp_path / f"data_{unique}"
    data_dir.mkdir(parents=True, exist_ok=True)
    cfg["paths"]["data_dir"] = str(data_dir)
    if db_path is not None:
        shutil.copy2(db_path, data_dir / "tradalgo.db")
    config_path = tmp_path / f"config_{unique}.yaml"
    with open(config_path, "w") as f:
        yaml.safe_dump(cfg, f)
    return config_path


def make_seeded_config(tmp_path: Path):
    db_path = _tmp_db_path()
    engine = make_engine(db_path)
    init_db(engine)
    ids = seed(engine)
    engine.dispose()
    config_path = make_config(tmp_path, db_path)
    return config_path, ids


def make_empty_config(tmp_path: Path):
    db_path = _tmp_db_path()
    engine = make_engine(db_path)
    init_db(engine)
    engine.dispose()
    return make_config(tmp_path, db_path)
