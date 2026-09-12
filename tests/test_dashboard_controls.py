import tempfile
import uuid
from datetime import datetime
from pathlib import Path

import pytest
import yaml
from sqlalchemy import insert, select

from tradalgo.clock import IST
from tradalgo.dashboard import controls
from tradalgo.storage.db import init_db, make_engine
from tradalgo.storage.schema import alerts, backtest_runs

NOW = datetime(2026, 9, 10, 9, 30, tzinfo=IST)

VALID_PARAMS = {
    "from": "2026-01-01", "to": "2026-06-30", "universe": "nifty50",
    "strategies": ["orb", "gap"], "shortlist_size": 6, "slippage_pct": 0.05,
    "max_risk_pct": 0.02, "initial_capital": 20000,
}


def _tmp_db_path() -> Path:
    return Path(tempfile.gettempdir()) / f"tradalgo_ctrl_{uuid.uuid4().hex}.db"


def make_engine_fixture():
    engine = make_engine(_tmp_db_path())
    init_db(engine)
    return engine


def test_kill_switch_toggle(tmp_path):
    assert not controls.kill_switch_active(tmp_path)
    controls.set_kill_switch(tmp_path, True)
    assert controls.kill_switch_active(tmp_path)
    controls.set_kill_switch(tmp_path, False)
    assert not controls.kill_switch_active(tmp_path)


def test_queue_backtest_valid():
    engine = make_engine_fixture()
    run_id = controls.queue_backtest(engine, VALID_PARAMS, NOW)
    with engine.connect() as conn:
        row = conn.execute(select(backtest_runs).where(backtest_runs.c.id == run_id)).one()
    assert row.status == "queued"


@pytest.mark.parametrize("bad_key,bad_value", [
    ("universe", "nifty500"),
    ("strategies", ["not_a_strategy"]),
    ("strategies", []),
    ("shortlist_size", 3),
    ("max_risk_pct", 0.05),
    ("initial_capital", -1),
])
def test_queue_backtest_rejects_invalid(bad_key, bad_value):
    engine = make_engine_fixture()
    params = dict(VALID_PARAMS, **{bad_key: bad_value})
    with pytest.raises(ValueError):
        controls.queue_backtest(engine, params, NOW)


def test_cancel_queued_goes_straight_to_cancelled():
    engine = make_engine_fixture()
    run_id = controls.queue_backtest(engine, VALID_PARAMS, NOW)
    controls.request_cancel_backtest(engine, run_id)
    with engine.connect() as conn:
        status = conn.execute(select(backtest_runs.c.status).where(backtest_runs.c.id == run_id)).scalar()
    assert status == "cancelled"


def test_cancel_running_requests_cancel():
    engine = make_engine_fixture()
    run_id = controls.queue_backtest(engine, VALID_PARAMS, NOW)
    with engine.begin() as conn:
        conn.execute(backtest_runs.update().where(backtest_runs.c.id == run_id).values(status="running"))
    controls.request_cancel_backtest(engine, run_id)
    with engine.connect() as conn:
        status = conn.execute(select(backtest_runs.c.status).where(backtest_runs.c.id == run_id)).scalar()
    assert status == "cancel_requested"


def test_cancel_done_run_is_noop():
    engine = make_engine_fixture()
    run_id = controls.queue_backtest(engine, VALID_PARAMS, NOW)
    with engine.begin() as conn:
        conn.execute(backtest_runs.update().where(backtest_runs.c.id == run_id).values(status="done"))
    controls.request_cancel_backtest(engine, run_id)
    with engine.connect() as conn:
        status = conn.execute(select(backtest_runs.c.status).where(backtest_runs.c.id == run_id)).scalar()
    assert status == "done"


def test_resend_alert_only_from_failed():
    engine = make_engine_fixture()
    with engine.begin() as conn:
        failed_id = conn.execute(insert(alerts).values(
            dedup_key="a", alert_type="entry", text="x", status="failed",
            created_at="2026-09-10T09:30:00+05:30", attempts=1,
        )).inserted_primary_key[0]
        sent_id = conn.execute(insert(alerts).values(
            dedup_key="b", alert_type="entry", text="y", status="sent",
            created_at="2026-09-10T09:30:00+05:30", attempts=1,
        )).inserted_primary_key[0]

    assert controls.resend_alert(engine, failed_id) is True
    assert controls.resend_alert(engine, sent_id) is False

    with engine.connect() as conn:
        assert conn.execute(select(alerts.c.status).where(alerts.c.id == failed_id)).scalar() == "queued"
        assert conn.execute(select(alerts.c.status).where(alerts.c.id == sent_id)).scalar() == "sent"


VALID_CONFIG = yaml.safe_load(open("config.yaml"))


def test_save_settings_writes_backup_and_new_file(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(VALID_CONFIG))

    new_config = dict(VALID_CONFIG)
    new_config["capital"] = dict(VALID_CONFIG["capital"], initial_capital=30000)
    controls.save_settings(config_path, new_config)

    backups = list(tmp_path.glob("config.yaml.bak-*"))
    assert len(backups) == 1
    assert yaml.safe_load(backups[0].read_text())["capital"]["initial_capital"] == 20000
    assert yaml.safe_load(config_path.read_text())["capital"]["initial_capital"] == 30000


def test_save_settings_rejects_invalid_and_leaves_file_untouched(tmp_path):
    config_path = tmp_path / "config.yaml"
    original_text = yaml.safe_dump(VALID_CONFIG)
    config_path.write_text(original_text)

    bad_config = dict(VALID_CONFIG)
    bad_config["capital"] = dict(VALID_CONFIG["capital"], max_risk_pct=1.0)  # > 0.03, invalid

    with pytest.raises(Exception):
        controls.save_settings(config_path, bad_config)

    assert config_path.read_text() == original_text
    assert list(tmp_path.glob("config.yaml.bak-*")) == []
