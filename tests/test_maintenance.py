from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import insert, select

from tradalgo.clock import IST, FixedClock
from tradalgo.jobs.maintenance import prune_old_data, rotate_logs, run_maintenance, token_expiry_reminder
from tradalgo.storage import repo
from tradalgo.storage.db import init_db, make_engine
from tradalgo.storage.schema import (
    alerts, backtest_runs, backtest_trades, decisions, health_events, paper_trades, signals, user_actions,
)

NOW = datetime(2026, 9, 13, 7, 0, tzinfo=IST)


class MemoryStore(dict):
    def get(self, name, default=None):
        return super().get(name, default)

    def set(self, name, value):
        self[name] = value


@pytest.fixture
def engine(tmp_path):
    eng = make_engine(tmp_path / "t.db")
    init_db(eng)
    return eng


# ---- token_expiry_reminder ----

def test_missing_refresh_token_triggers_reminder(engine):
    store = MemoryStore()
    msg = token_expiry_reminder(engine, store, FixedClock(NOW))
    assert msg is not None and "tradalgo login" in msg
    with engine.connect() as conn:
        assert conn.execute(select(alerts)).mappings().one()["dedup_key"] == "token-expiry:missing"
        event = conn.execute(select(health_events)).mappings().one()
        assert event["component"] == "fyers" and event["level"] == "warning"


def test_expiring_soon_triggers_reminder(engine):
    store = MemoryStore(FYERS_REFRESH_TOKEN_ISSUED=(NOW.date() - timedelta(days=14)).isoformat())
    msg = token_expiry_reminder(engine, store, FixedClock(NOW), days_before=2)
    assert msg is not None


def test_far_from_expiry_no_reminder(engine):
    store = MemoryStore(FYERS_REFRESH_TOKEN_ISSUED=NOW.date().isoformat())
    assert token_expiry_reminder(engine, store, FixedClock(NOW), days_before=2) is None
    with engine.connect() as conn:
        assert conn.execute(select(alerts)).first() is None


def test_repeated_calls_enqueue_only_one_alert(engine):
    store = MemoryStore()
    for _ in range(3):
        token_expiry_reminder(engine, store, FixedClock(NOW))
    with engine.connect() as conn:
        assert conn.execute(select(alerts)).all().__len__() == 1


# ---- rotate_logs ----

def test_rotate_logs_missing_dir_returns_empty(tmp_path):
    assert rotate_logs(tmp_path / "nope") == []


def test_rotate_logs_leaves_small_files_alone(tmp_path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    f = log_dir / "app.log"
    f.write_text("small")
    assert rotate_logs(log_dir, max_bytes=1000) == []
    assert f.exists() and f.read_text() == "small"


def test_rotate_logs_non_log_files_untouched(tmp_path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    big = log_dir / "app.log"
    big.write_text("x" * 100)
    other = log_dir / "notes.txt"
    other.write_text("x" * 100)
    rotate_logs(log_dir, max_bytes=10)
    assert other.exists() and other.read_text() == "x" * 100
    assert big.exists() and big.read_text() == ""  # truncated in place, not renamed away
    assert (log_dir / "app.log.1").exists()


def test_rotate_logs_shifts_and_caps_at_keep(tmp_path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "app.log.1").write_text("gen1")
    (log_dir / "app.log.2").write_text("gen2")
    (log_dir / "app.log").write_text("x" * 100)
    rotated = rotate_logs(log_dir, max_bytes=10, keep=2)
    assert rotated == [log_dir / "app.log.1"]
    assert (log_dir / "app.log.1").read_text() == "x" * 100
    assert (log_dir / "app.log.2").read_text() == "gen1"
    assert not (log_dir / "app.log.3").exists()
    assert (log_dir / "app.log").exists() and (log_dir / "app.log").read_text() == ""


def test_rotate_logs_safe_for_an_open_append_writer(tmp_path):
    """launchd holds StandardOutPath open with O_APPEND for the job's lifetime; rotation must
    not break that handle the way a rename would."""
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    path = log_dir / "app.log"
    path.write_text("x" * 100)

    with open(path, "a") as writer:
        rotated = rotate_logs(log_dir, max_bytes=10, keep=3)
        assert rotated == [log_dir / "app.log.1"]
        writer.write("new-entry")
        writer.flush()

    assert path.read_text() == "new-entry"
    assert (log_dir / "app.log.1").read_text() == "x" * 100


# ---- prune_old_data ----

def _iso(d: str) -> str:
    return f"{d}T00:00:00+05:30"


def test_prune_deletes_old_health_events_only(engine):
    with engine.begin() as conn:
        conn.execute(insert(health_events).values(
            ts=_iso("2024-01-01"), component="worker", level="info", message="old"))
        conn.execute(insert(health_events).values(
            ts=_iso("2026-09-01"), component="worker", level="info", message="recent"))
    result = prune_old_data(engine, FixedClock(NOW), keep_days=365)
    assert result["health_events_deleted"] == 1
    with engine.connect() as conn:
        remaining = conn.execute(select(health_events)).mappings().all()
    assert len(remaining) == 1 and remaining[0]["message"] == "recent"


def _seed_backtest_signal(engine, run_id, status, created_at):
    with engine.begin() as conn:
        conn.execute(insert(backtest_runs).values(
            id=run_id, created_at=created_at, status=status, params_json="{}", progress_pct=0))
        conn.execute(insert(signals).values(
            id=run_id, ts=created_at, symbol="X", strategy="orb", direction="long", regime="trend_up",
            entry=1.0, stop_loss=0.5, target_2r=2.0, target_3r=3.0, features_json="{}", mode="backtest",
            backtest_run_id=run_id,
        ))
        conn.execute(insert(decisions).values(signal_id=run_id, accepted=0))


def test_prune_removes_signals_and_decisions_of_old_failed_backtest_runs(engine):
    _seed_backtest_signal(engine, 1, "failed", _iso("2026-01-01"))
    result = prune_old_data(engine, FixedClock(NOW), keep_days=365)
    assert result["signals_deleted"] == 1 and result["decisions_deleted"] == 1
    with engine.connect() as conn:
        assert conn.execute(select(signals)).first() is None
        assert conn.execute(select(decisions)).first() is None
        assert conn.execute(select(backtest_runs)).first() is not None  # run row itself is kept


def _insert_backtest_trade(engine, run_id, signal_id):
    with engine.begin() as conn:
        conn.execute(insert(backtest_trades).values(
            backtest_run_id=run_id, signal_id=signal_id, trade_date="2026-01-01", symbol="X",
            strategy="orb", direction="long", entry_ts=_iso("2026-01-01"), entry_price=1.0,
            exit_ts=_iso("2026-01-01"), exit_price=1.1, exit_reason="target", qty=1,
            gross_r=1.0, net_r=1.0,
        ))


def test_prune_removes_backtest_trades_leaving_no_orphaned_fk_rows(engine):
    _seed_backtest_signal(engine, 1, "cancelled", _iso("2026-01-01"))
    _insert_backtest_trade(engine, run_id=1, signal_id=1)

    result = prune_old_data(engine, FixedClock(NOW), keep_days=365)

    assert result["backtest_trades_deleted"] == 1
    with engine.connect() as conn:
        assert conn.execute(select(backtest_trades)).first() is None
        # LEFT JOIN orphan check: no backtest_trades row should reference a missing signal.
        orphans = conn.execute(
            select(backtest_trades.c.id)
            .select_from(backtest_trades.outerjoin(signals, backtest_trades.c.signal_id == signals.c.id))
            .where(signals.c.id.is_(None), backtest_trades.c.signal_id.isnot(None))
        ).all()
        assert orphans == []
        assert conn.execute(select(backtest_runs)).first() is not None  # run row itself is kept


def test_prune_never_touches_recent_or_done_backtest_signals(engine):
    _seed_backtest_signal(engine, 1, "failed", _iso("2026-09-10"))  # too recent
    _seed_backtest_signal(engine, 2, "done", _iso("2026-01-01"))  # completed, protected
    _insert_backtest_trade(engine, run_id=2, signal_id=2)
    result = prune_old_data(engine, FixedClock(NOW), keep_days=365)
    assert result["signals_deleted"] == 0 and result["backtest_trades_deleted"] == 0
    with engine.connect() as conn:
        assert len(conn.execute(select(signals)).all()) == 2
        assert len(conn.execute(select(backtest_trades)).all()) == 1


def test_prune_never_touches_live_signals_alerts_actions_or_paper_trades(engine):
    with engine.begin() as conn:
        conn.execute(insert(signals).values(
            id=99, ts=_iso("2020-01-01"), symbol="X", strategy="orb", direction="long", regime="trend_up",
            entry=1.0, stop_loss=0.5, target_2r=2.0, target_3r=3.0, features_json="{}", mode="live",
        ))
        conn.execute(insert(paper_trades).values(
            signal_id=99, taken_by_user=1, entry_ts=_iso("2020-01-01"), entry_price=1.0, qty=1))
        alert_id = conn.execute(insert(alerts).values(
            dedup_key="k1", alert_type="entry", text="t", status="sent", created_at=_iso("2020-01-01"),
            attempts=0,
        )).inserted_primary_key[0]
        conn.execute(insert(user_actions).values(alert_id=alert_id, action="taken", ts=_iso("2020-01-01")))
    prune_old_data(engine, FixedClock(NOW), keep_days=1)
    with engine.connect() as conn:
        assert conn.execute(select(signals)).first() is not None
        assert conn.execute(select(paper_trades)).first() is not None
        assert conn.execute(select(alerts)).first() is not None
        assert conn.execute(select(user_actions)).first() is not None


# ---- run_maintenance ----

def test_run_maintenance_calls_all_three(engine, settings, tmp_path):
    settings = settings.model_copy(update={"paths": settings.paths.model_copy(update={"data_dir": tmp_path})})
    store = MemoryStore()
    result = run_maintenance(settings, engine, store, FixedClock(NOW))
    assert set(result) == {"token_expiry_message", "rotated_logs", "pruned"}
    assert result["rotated_logs"] == []
