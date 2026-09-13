"""Offline tests for the session/backtest/worker/report CLI commands: no network, no keychain, no Telegram."""
import json
from argparse import Namespace
from datetime import date, datetime

import yaml
from sqlalchemy import insert, select, update

from tradalgo import cli
from tradalgo.clock import IST, FixedClock
from tradalgo.storage import repo
from tradalgo.storage.db import init_db, make_engine
from tradalgo.storage.schema import alerts, backtest_runs, health_events, shortlist

from tests.backtest_fixtures import REPLAY_DAYS, build_replay_cache, universe as make_universe

UNIVERSE_CSV = "Symbol,Company Name,Industry,Series\nSBIN,State Bank,Financials,EQ\nTCS,TCS Ltd,IT,EQ\n"


def _setup(tmp_path, raw_config, monkeypatch, now=datetime(2026, 9, 15, 8, 0, tzinfo=IST)):
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "nifty50.csv").write_text(UNIVERSE_CSV)
    (static_dir / "niftynext50.csv").write_text("Symbol,Company Name,Industry,Series\n")
    raw_config["paths"]["data_dir"] = str(tmp_path / "data")
    raw_config["paths"]["static_dir"] = str(static_dir)
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.safe_dump(raw_config))

    settings = cli.load_settings(cfg_path)
    settings.paths.data_dir.mkdir(parents=True, exist_ok=True)
    engine = make_engine(settings.paths.db_path)
    init_db(engine)

    monkeypatch.setattr(cli, "clock_factory", lambda: FixedClock(now))
    monkeypatch.setattr(cli, "store_factory", lambda: object())
    return cfg_path, settings, engine


# ---------- session ----------

def test_session_skips_on_non_trading_day(tmp_path, raw_config, monkeypatch, capsys):
    cfg_path, settings, engine = _setup(tmp_path, raw_config, monkeypatch)
    # 2026-09-13 is a Sunday
    assert cli.main(["--config", str(cfg_path), "session", "--date", "2026-09-13"]) == 0
    assert "not a trading day" in capsys.readouterr().out


def test_session_skips_when_shortlist_empty(tmp_path, raw_config, monkeypatch, capsys):
    cfg_path, settings, engine = _setup(tmp_path, raw_config, monkeypatch)
    # 2026-09-15 is a Tuesday with no shortlist rows seeded
    assert cli.main(["--config", str(cfg_path), "session", "--date", "2026-09-15"]) == 0
    assert "no shortlist" in capsys.readouterr().out


# ---------- backtest ----------

def _backtest_args(frm, to):
    return ["backtest", "--from", frm.isoformat(), "--to", to.isoformat(), "--universe", "nifty50",
           "--strategies", "orb,gap,vwap,pdhl,pullback,range_breakout", "--shortlist-size", "6",
           "--slippage-pct", "0.05", "--max-risk-pct", "0.03", "--capital", "20000"]


def test_backtest_end_to_end_prints_metrics_and_fail_gate(tmp_path, raw_config, monkeypatch, capsys):
    cfg_path, settings, engine = _setup(tmp_path, raw_config, monkeypatch)
    build_replay_cache(settings.paths.data_dir / "candles")
    monkeypatch.setattr("tradalgo.data.universe.load_universe", lambda static_dir: make_universe(["AAA", "BBB", "CCC"]))

    rc = cli.main(["--config", str(cfg_path), *_backtest_args(REPLAY_DAYS[0], REPLAY_DAYS[-1])])
    out = capsys.readouterr().out
    assert rc == 0
    assert "trades:" in out
    assert "by_strategy:" in out
    assert "M6 gate: FAIL" in out  # too few trades on this tiny 3-day synthetic cache


def test_backtest_missing_data_prints_backfill_hint_and_exits_nonzero(tmp_path, raw_config, monkeypatch, capsys):
    cfg_path, settings, engine = _setup(tmp_path, raw_config, monkeypatch)
    # No candle cache populated at all.
    monkeypatch.setattr("tradalgo.data.universe.load_universe", lambda static_dir: make_universe(["AAA", "BBB", "CCC"]))

    rc = cli.main(["--config", str(cfg_path), *_backtest_args(REPLAY_DAYS[0], REPLAY_DAYS[-1])])
    captured = capsys.readouterr()
    assert rc == 1
    assert "backfill" in (captured.out + captured.err)


def _minimal_metrics(**overrides) -> dict:
    m = {"trades": 0, "win_rate": 0.0, "expectancy_r": 0.0, "expectancy_r_no_slippage": 0.0,
        "profit_factor": None, "max_drawdown_r": 0.0, "net_r": 0.0, "net_rupees": 0.0,
        "by_strategy": {}, "by_regime": {}, "missed_entries": 0, "fill_rate": None, "missed": []}
    m.update(overrides)
    return m


def test_backtest_processes_only_its_own_run_leaves_others_queued(tmp_path, raw_config, monkeypatch, capsys):
    cfg_path, settings, engine = _setup(tmp_path, raw_config, monkeypatch)
    build_replay_cache(settings.paths.data_dir / "candles")
    monkeypatch.setattr("tradalgo.data.universe.load_universe", lambda static_dir: make_universe(["AAA", "BBB", "CCC"]))

    other_run_id = repo.enqueue_backtest_run(engine, {"from": "2020-01-01"}, datetime(2026, 9, 15, 7, 0, tzinfo=IST))

    rc = cli.main(["--config", str(cfg_path), *_backtest_args(REPLAY_DAYS[0], REPLAY_DAYS[-1])])
    assert rc == 0

    with engine.connect() as conn:
        other_status = conn.execute(select(backtest_runs.c.status)
                                    .where(backtest_runs.c.id == other_run_id)).scalar()
    assert other_status == "queued"  # untouched: cmd_backtest must not drain the whole FIFO


def test_backtest_waits_when_worker_claimed_the_run_first(tmp_path, raw_config, monkeypatch, capsys):
    cfg_path, settings, engine = _setup(tmp_path, raw_config, monkeypatch)
    monkeypatch.setattr("tradalgo.data.universe.load_universe", lambda static_dir: make_universe(["AAA"]))
    # simulate a concurrent `tradalgo worker` winning the claim race
    monkeypatch.setattr("tradalgo.storage.repo.claim_backtest_run", lambda engine_, run_id, now: False)

    poll_calls = []

    def fake_sleep(seconds):
        poll_calls.append(seconds)
        if len(poll_calls) >= 2:
            with engine.begin() as conn:
                run_id = conn.execute(select(backtest_runs.c.id).order_by(backtest_runs.c.id.desc())
                                      .limit(1)).scalar()
                conn.execute(update(backtest_runs).where(backtest_runs.c.id == run_id).values(
                    status="done", progress_pct=100.0, metrics_json=json.dumps(_minimal_metrics()),
                    finished_at="2026-09-15T10:00:00+05:30"))

    monkeypatch.setattr(cli, "backtest_poll_sleep", fake_sleep)
    monkeypatch.setattr(cli, "backtest_poll_seconds", 0)

    rc = cli.main(["--config", str(cfg_path), *_backtest_args(REPLAY_DAYS[0], REPLAY_DAYS[-1])])
    out = capsys.readouterr().out
    assert rc == 0
    assert "being processed by the worker" in out
    assert "trades: 0" in out
    assert len(poll_calls) >= 2


def test_backtest_ctrl_c_while_processing_marks_run_cancelled(tmp_path, raw_config, monkeypatch, capsys):
    cfg_path, settings, engine = _setup(tmp_path, raw_config, monkeypatch)
    monkeypatch.setattr("tradalgo.data.universe.load_universe", lambda static_dir: make_universe(["AAA"]))

    def raising_process_run(*a, **kw):
        raise KeyboardInterrupt

    monkeypatch.setattr("tradalgo.jobs.backtest_worker.process_run", raising_process_run)

    rc = cli.main(["--config", str(cfg_path), *_backtest_args(REPLAY_DAYS[0], REPLAY_DAYS[-1])])
    captured = capsys.readouterr()
    assert rc == 130
    assert "interrupted" in (captured.out + captured.err)

    with engine.connect() as conn:
        row = conn.execute(select(backtest_runs.c.status, backtest_runs.c.error, backtest_runs.c.finished_at)
                           .order_by(backtest_runs.c.id.desc()).limit(1)).mappings().first()
    assert row["status"] == "cancelled"
    assert row["error"] == "interrupted by user"
    assert row["finished_at"]


def test_backtest_ctrl_c_while_waiting_does_not_touch_row(tmp_path, raw_config, monkeypatch, capsys):
    cfg_path, settings, engine = _setup(tmp_path, raw_config, monkeypatch)
    monkeypatch.setattr("tradalgo.data.universe.load_universe", lambda static_dir: make_universe(["AAA"]))
    monkeypatch.setattr("tradalgo.storage.repo.claim_backtest_run", lambda engine_, run_id, now: False)

    def raising_sleep(seconds):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "backtest_poll_sleep", raising_sleep)
    monkeypatch.setattr(cli, "backtest_poll_seconds", 0)

    rc = cli.main(["--config", str(cfg_path), *_backtest_args(REPLAY_DAYS[0], REPLAY_DAYS[-1])])
    assert rc == 130

    with engine.connect() as conn:
        status = conn.execute(select(backtest_runs.c.status).order_by(backtest_runs.c.id.desc())
                              .limit(1)).scalar()
    assert status == "queued"  # left for the worker; we never claimed or touched it


def test_backtest_prints_na_for_none_metrics(tmp_path, raw_config, monkeypatch, capsys):
    cfg_path, settings, engine = _setup(tmp_path, raw_config, monkeypatch)
    build_replay_cache(settings.paths.data_dir / "candles")
    monkeypatch.setattr("tradalgo.data.universe.load_universe", lambda static_dir: make_universe(["AAA", "BBB", "CCC"]))

    # The synthetic replay cache with real detectors produces 0 trades, so profit_factor and fill_rate are None.
    rc = cli.main(["--config", str(cfg_path), *_backtest_args(REPLAY_DAYS[0], REPLAY_DAYS[-1])])
    out = capsys.readouterr().out
    assert rc == 0
    assert "n/a" in out
    assert "None" not in out


def test_backtest_rejects_invalid_params(tmp_path, raw_config, monkeypatch, capsys):
    cfg_path, settings, engine = _setup(tmp_path, raw_config, monkeypatch)
    rc = cli.main(["--config", str(cfg_path), "backtest", "--from", "2026-09-15", "--to", "2026-09-17",
                  "--universe", "both", "--strategies", "not_a_real_strategy", "--shortlist-size", "6",
                  "--max-risk-pct", "0.02", "--capital", "20000"])
    assert rc == 1
    assert "invalid backtest params" in capsys.readouterr().err


# ---------- worker ----------

def test_worker_loop_runs_once_and_survives_polling_exception(tmp_path, raw_config, monkeypatch, capsys):
    cfg_path, settings, engine = _setup(tmp_path, raw_config, monkeypatch)

    class FakeStore:
        def get(self, name):
            return {"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": "123"}.get(name)

    monkeypatch.setattr(cli, "store_factory", FakeStore)

    calls = {"run_worker": 0, "poll": 0, "maintenance": 0}

    def fake_run_worker(settings_, engine_, clock_, *, once, telegram_client):
        calls["run_worker"] += 1
        assert once is True

    def fake_poll(*a, **kw):
        calls["poll"] += 1
        raise RuntimeError("telegram is down")

    def fake_maintenance(settings_, engine_, store_, clock_):
        calls["maintenance"] += 1
        return {}

    monkeypatch.setattr("tradalgo.jobs.backtest_worker.run_worker", fake_run_worker)
    monkeypatch.setattr("tradalgo.engine.session.poll_telegram_updates", fake_poll)
    monkeypatch.setattr("tradalgo.jobs.maintenance.run_maintenance", fake_maintenance)

    def stop_after_one_iteration(seconds):
        raise KeyboardInterrupt

    monkeypatch.setattr("time.sleep", stop_after_one_iteration)

    rc = cli.main(["--config", str(cfg_path), "worker"])
    assert rc == 0
    assert calls["run_worker"] == 1
    assert calls["poll"] == 1
    assert calls["maintenance"] == 1  # once at startup

    with engine.connect() as conn:
        rows = conn.execute(select(health_events.c.message).where(
            health_events.c.component == "worker")).scalars().all()
    assert any("telegram poll failed" in m for m in rows)


def test_worker_survives_run_worker_exception_and_keeps_looping(tmp_path, raw_config, monkeypatch, capsys):
    cfg_path, settings, engine = _setup(tmp_path, raw_config, monkeypatch)

    class FakeStore:
        def get(self, name):
            return None

    monkeypatch.setattr(cli, "store_factory", FakeStore)

    calls = {"run_worker": 0, "poll": 0, "maintenance": 0, "sleep": 0}

    def fake_run_worker(settings_, engine_, clock_, *, once, telegram_client):
        calls["run_worker"] += 1
        raise RuntimeError("db is locked")

    def fake_poll(*a, **kw):
        calls["poll"] += 1

    def fake_maintenance(settings_, engine_, store_, clock_):
        calls["maintenance"] += 1
        return {}

    def fake_sleep(seconds):
        calls["sleep"] += 1
        if calls["sleep"] >= 2:
            raise KeyboardInterrupt

    monkeypatch.setattr("tradalgo.jobs.backtest_worker.run_worker", fake_run_worker)
    monkeypatch.setattr("tradalgo.engine.session.poll_telegram_updates", fake_poll)
    monkeypatch.setattr("tradalgo.jobs.maintenance.run_maintenance", fake_maintenance)
    monkeypatch.setattr("time.sleep", fake_sleep)

    rc = cli.main(["--config", str(cfg_path), "worker"])
    assert rc == 0
    assert calls["run_worker"] >= 1
    assert calls["sleep"] >= 2  # the loop kept going after run_worker's exception

    with engine.connect() as conn:
        rows = conn.execute(select(health_events.c.message).where(
            health_events.c.component == "worker")).scalars().all()
    assert any("run_worker failed" in m for m in rows)


# ---------- report ----------

def test_report_prints_text_and_enqueues_one_alert_with_telegram(tmp_path, raw_config, monkeypatch, capsys):
    cfg_path, settings, engine = _setup(tmp_path, raw_config, monkeypatch)

    rc1 = cli.main(["--config", str(cfg_path), "report", "--weeks", "1", "--telegram"])
    out1 = capsys.readouterr().out
    assert rc1 == 0
    assert "Weekly Report" in out1

    rc2 = cli.main(["--config", str(cfg_path), "report", "--weeks", "1", "--telegram"])
    assert rc2 == 0
    capsys.readouterr()

    with engine.connect() as conn:
        count = conn.execute(select(alerts.c.id).where(alerts.c.alert_type == "report")).all()
    assert len(count) == 1  # dedup key collapses the second call into a no-op


# ---------- live sink receives configured costs ----------

def _capture_sink(monkeypatch, start_ok):
    import tradalgo.engine.session as session_mod
    captured = {}

    class FakeSession:
        def __init__(self, settings, engine, clock, provider, cache, sink_factory, **kw):
            captured["sink"] = sink_factory(lambda: False)

        def start(self, trade_date):
            return start_ok

    monkeypatch.setattr(session_mod, "LiveSession", FakeSession)
    monkeypatch.setattr(session_mod, "shortlist_symbols", lambda engine, d: ["SBIN"])
    monkeypatch.setattr(session_mod, "run_session", lambda *a, **k: True)
    monkeypatch.setattr(cli, "build_screen_provider", lambda *a, **k: None)
    monkeypatch.setattr(cli, "build_tick_stream_factory", lambda *a, **k: None)
    return captured


def test_session_and_ci_cycle_live_sink_get_settings_costs(tmp_path, raw_config, monkeypatch):
    raw_config["costs"] = {"brokerage_cap_per_order": 7.0}
    cfg_path, settings, engine = _setup(tmp_path, raw_config, monkeypatch,
                                        now=datetime(2026, 9, 15, 10, 0, tzinfo=IST))
    captured = _capture_sink(monkeypatch, start_ok=True)
    assert cli.cmd_session(settings, Namespace(date="2026-09-15")) == 0
    assert captured.pop("sink").costs.brokerage_cap_per_order == 7.0
    captured = _capture_sink(monkeypatch, start_ok=False)
    assert cli.cmd_ci_cycle(settings, Namespace(date="2026-09-15")) == 0
    assert captured["sink"].costs.brokerage_cap_per_order == 7.0
