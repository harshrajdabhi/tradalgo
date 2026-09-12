from datetime import date, datetime

import pytest
from sqlalchemy import select, text

from tradalgo.clock import IST
from tradalgo.storage import repo
from tradalgo.storage.db import init_db, make_engine
from tradalgo.storage.schema import alerts

NOW = datetime(2026, 9, 11, 9, 20, tzinfo=IST)


@pytest.fixture
def engine(tmp_path):
    eng = make_engine(tmp_path / "t.db")
    init_db(eng)
    return eng


def test_wal_and_foreign_keys_enabled(engine):
    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA journal_mode")).scalar() == "wal"
        assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1


def test_job_idempotency(engine):
    assert not repo.has_job_succeeded_on(engine, "screen", date(2026, 9, 11))
    run_id = repo.start_job_run(engine, "screen", NOW)
    assert not repo.has_job_succeeded_on(engine, "screen", date(2026, 9, 11))
    repo.finish_job_run(engine, run_id, NOW)
    assert repo.has_job_succeeded_on(engine, "screen", date(2026, 9, 11))
    assert not repo.has_job_succeeded_on(engine, "preopen", date(2026, 9, 11))


def test_failed_job_does_not_count_as_success(engine):
    run_id = repo.start_job_run(engine, "screen", NOW)
    repo.finish_job_run(engine, run_id, NOW, error="FYERS down")
    assert not repo.has_job_succeeded_on(engine, "screen", date(2026, 9, 11))


def test_alert_dedup_and_status_transitions(engine):
    alert_id = repo.enqueue_alert(engine, "RELIANCE:orb:entry:2026-09-11T09:35", "entry", "BUY", NOW, "RELIANCE")
    assert alert_id is not None
    assert repo.enqueue_alert(engine, "RELIANCE:orb:entry:2026-09-11T09:35", "entry", "BUY", NOW) is None

    repo.mark_alert_failed(engine, alert_id, "timeout")
    repo.mark_alert_sent(engine, alert_id, message_id=42, now=NOW, latency_ms=180)
    with engine.connect() as conn:
        row = conn.execute(select(alerts).where(alerts.c.id == alert_id)).mappings().one()
    assert row["status"] == "sent"
    assert row["attempts"] == 2
    assert row["telegram_message_id"] == 42
    assert row["last_error"] is None
    assert row["sent_at"] == "2026-09-11T09:20:00+05:30"


def test_backtest_claim_is_exclusive_and_fifo(engine):
    first = repo.enqueue_backtest_run(engine, {"from": "2025-09-01"}, NOW)
    second = repo.enqueue_backtest_run(engine, {"from": "2026-01-01"}, NOW)
    assert repo.claim_next_backtest_run(engine, NOW) == first
    assert repo.claim_next_backtest_run(engine, NOW) == second
    assert repo.claim_next_backtest_run(engine, NOW) is None


def test_naive_timestamps_rejected(engine):
    with pytest.raises(ValueError, match="naive"):
        repo.start_job_run(engine, "screen", datetime(2026, 9, 11, 9, 20))
