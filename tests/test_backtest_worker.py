import json
from datetime import datetime

import pytest
from sqlalchemy import func, select, update

from tradalgo.backtest.replay import BacktestCancelled
from tradalgo.clock import IST, FixedClock
from tradalgo.jobs.backtest_worker import build_telegram_client, run_worker
from tradalgo.storage import repo
from tradalgo.storage.db import init_db, make_engine
from tradalgo.storage.schema import alerts, backtest_runs, health_events

NOW = datetime(2026, 9, 13, 18, 0, tzinfo=IST)
METRICS = {"trades": 0, "win_rate": 0.0, "expectancy_r": 0.0, "expectancy_r_no_slippage": 0.0,
           "profit_factor": None, "max_drawdown_r": 0.0, "net_r": 0.0, "net_rupees": 0.0,
           "by_strategy": {}, "by_regime": {}}


@pytest.fixture
def engine(tmp_path):
    eng = make_engine(tmp_path / "t.db")
    init_db(eng)
    return eng


def _row(engine, run_id):
    with engine.connect() as conn:
        return conn.execute(select(backtest_runs).where(backtest_runs.c.id == run_id)).mappings().one()


def _work(settings, engine, runner, **kw):
    run_worker(settings, engine, FixedClock(NOW), once=True, runner=runner, cache=object(), universe=[], **kw)


def test_queued_running_done(settings, engine):
    run_id = repo.enqueue_backtest_run(engine, {"from": "2026-09-01"}, NOW)
    seen = {}

    def runner(settings, engine_, params, rid, cache, universe, progress_cb, cancel_cb):
        seen["status"], seen["params"] = _row(engine, rid)["status"], params
        progress_cb(50.0)
        seen["progress"] = _row(engine, rid)["progress_pct"]
        return METRICS

    _work(settings, engine, runner)
    row = _row(engine, run_id)
    assert seen == {"status": "running", "params": {"from": "2026-09-01"}, "progress": 50.0}
    assert row["status"] == "done" and row["progress_pct"] == 100.0 and row["finished_at"]
    assert json.loads(row["metrics_json"]) == METRICS


def test_failure_recorded_and_worker_continues(settings, engine):
    first = repo.enqueue_backtest_run(engine, {}, NOW)
    second = repo.enqueue_backtest_run(engine, {}, NOW)

    def runner(settings, engine_, params, rid, *rest):
        if rid == first:
            raise ValueError("no 5m candles for AAA")
        return METRICS

    _work(settings, engine, runner)
    assert _row(engine, first)["status"] == "failed"
    assert "ValueError: no 5m candles for AAA" in _row(engine, first)["error"]
    assert _row(engine, second)["status"] == "done"


def test_cancel_requested_becomes_cancelled(settings, engine):
    run_id = repo.enqueue_backtest_run(engine, {}, NOW)

    def runner(settings, engine_, params, rid, cache, universe, progress_cb, cancel_cb):
        assert cancel_cb() is False
        with engine.begin() as conn:
            conn.execute(update(backtest_runs).where(backtest_runs.c.id == rid).values(status="cancel_requested"))
        if cancel_cb():
            raise BacktestCancelled("cancelled")
        return METRICS

    _work(settings, engine, runner)
    row = _row(engine, run_id)
    assert row["status"] == "cancelled" and row["finished_at"] and row["metrics_json"] is None


class FakeClient:
    def __init__(self):
        self.sent = []

    def send_message(self, text, buttons=None):
        self.sent.append(text)
        return len(self.sent)

    def edit_message(self, message_id, text, buttons=None):
        pass


def test_sender_runs_when_client_given(settings, engine):
    repo.enqueue_alert(engine, "k1", "shortlist", "hello", NOW)
    client = FakeClient()
    _work(settings, engine, lambda *a: METRICS, telegram_client=client)
    assert client.sent == ["hello"]
    with engine.connect() as conn:
        assert conn.execute(select(alerts.c.status)).scalar() == "sent"


def test_missing_client_warns_once_and_keeps_processing(settings, engine):
    run_id = repo.enqueue_backtest_run(engine, {}, NOW)
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 3:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_worker(settings, engine, FixedClock(NOW), sleep=sleep, runner=lambda *a: METRICS, cache=object(),
                   universe=[])
    assert _row(engine, run_id)["status"] == "done"
    with engine.connect() as conn:
        warnings = conn.execute(select(func.count()).select_from(health_events).where(
            health_events.c.level == "warning", health_events.c.component == "worker")).scalar()
    assert warnings == 1


def test_build_telegram_client_needs_both_secrets():
    class Store(dict):
        def get(self, name):
            return super().get(name)

    assert build_telegram_client(Store(TELEGRAM_BOT_TOKEN="t")) is None
    assert build_telegram_client(Store(TELEGRAM_BOT_TOKEN="t", TELEGRAM_CHAT_ID="1")) is not None
