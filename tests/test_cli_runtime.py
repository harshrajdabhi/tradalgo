"""Offline tests for the session/backtest/worker/report CLI commands: no network, no keychain, no Telegram."""
import json
from datetime import date, datetime

import yaml
from sqlalchemy import insert, select

from tradalgo import cli
from tradalgo.clock import IST, FixedClock
from tradalgo.storage.db import init_db, make_engine
from tradalgo.storage.schema import alerts, health_events, shortlist

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
