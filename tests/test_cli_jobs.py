import sys
from datetime import date, datetime
from pathlib import Path

import yaml
from sqlalchemy import insert, select

from tradalgo import cli
from tradalgo.clock import IST, FixedClock
from tradalgo.data.base import empty_candles
from tradalgo.storage.db import init_db, make_engine
from tradalgo.storage.repo import finish_job_run, has_job_succeeded_on, start_job_run
from tradalgo.storage.schema import alerts, job_runs, shortlist


UNIVERSE_CSV = "Symbol,Company Name,Industry,Series\nSBIN,State Bank,Financials,EQ\nTCS,TCS Ltd,IT,EQ\n"


def _setup(tmp_path, raw_config, monkeypatch):
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

    monkeypatch.setattr("tradalgo.data.universe.refresh_constituents", lambda static_dir: [])
    monkeypatch.setattr(cli, "clock_factory", lambda: FixedClock(datetime(2026, 9, 14, 6, 0, tzinfo=IST)))
    monkeypatch.setattr(cli, "store_factory", lambda: object())
    return cfg_path, settings, engine


class FakeCandleProvider:
    degraded = False
    name = "fake"

    def get_candles(self, symbol, resolution, start, end):
        return empty_candles()


def test_screen_skips_on_non_trading_day(tmp_path, raw_config, monkeypatch, capsys):
    cfg_path, settings, engine = _setup(tmp_path, raw_config, monkeypatch)
    # 2026-09-13 is a Sunday
    assert cli.main(["--config", str(cfg_path), "screen", "--date", "2026-09-13"]) == 0
    assert "not a trading day" in capsys.readouterr().out


def test_screen_skips_if_already_succeeded_unless_forced(tmp_path, raw_config, monkeypatch, capsys):
    cfg_path, settings, engine = _setup(tmp_path, raw_config, monkeypatch)
    start_id = start_job_run(engine, "screen", datetime(2026, 9, 14, tzinfo=IST))
    finish_job_run(engine, start_id, datetime(2026, 9, 14, tzinfo=IST))
    assert has_job_succeeded_on(engine, "screen", date(2026, 9, 14))

    monkeypatch.setattr(cli, "build_screen_provider", lambda *a, **k: FakeCandleProvider())
    assert cli.main(["--config", str(cfg_path), "screen", "--date", "2026-09-14"]) == 0
    assert "already succeeded" in capsys.readouterr().out


def test_screen_runs_and_enqueues_shortlist_alert(tmp_path, raw_config, monkeypatch):
    cfg_path, settings, engine = _setup(tmp_path, raw_config, monkeypatch)
    monkeypatch.setattr(cli, "build_screen_provider", lambda *a, **k: FakeCandleProvider())

    class Pick:
        symbol, direction, composite_score, reasons = "SBIN", "long", 88.0, ["strong trend"]

    monkeypatch.setattr(cli, "run_screen", lambda *a, **k: [Pick()])
    assert cli.main(["--config", str(cfg_path), "screen", "--date", "2026-09-14"]) == 0

    with engine.connect() as conn:
        rows = conn.execute(select(alerts.c.dedup_key, alerts.c.alert_type)).all()
    assert ("shortlist:2026-09-14", "shortlist") in rows


def test_screen_records_failure_on_provider_error(tmp_path, raw_config, monkeypatch):
    cfg_path, settings, engine = _setup(tmp_path, raw_config, monkeypatch)

    def boom(*a, **k):
        raise RuntimeError("no fyers, no yfinance")

    monkeypatch.setattr(cli, "build_screen_provider", boom)
    assert cli.main(["--config", str(cfg_path), "screen", "--date", "2026-09-14"]) == 1
    assert not has_job_succeeded_on(engine, "screen", date(2026, 9, 14))


def _failed_screen_rows(engine):
    with engine.connect() as conn:
        return conn.execute(
            select(job_runs.c.id).where(job_runs.c.job == "screen", job_runs.c.status == "failed")
        ).all()


def _failed_preopen_rows(engine):
    with engine.connect() as conn:
        return conn.execute(
            select(job_runs.c.id).where(job_runs.c.job == "preopen", job_runs.c.status == "failed")
        ).all()


def test_screen_records_exactly_one_failure_row_for_pre_run_screen_failure(tmp_path, raw_config, monkeypatch):
    cfg_path, settings, engine = _setup(tmp_path, raw_config, monkeypatch)

    def boom(*a, **k):
        raise RuntimeError("provider setup blew up")

    monkeypatch.setattr(cli, "build_screen_provider", boom)
    assert cli.main(["--config", str(cfg_path), "screen", "--date", "2026-09-14"]) == 1
    assert len(_failed_screen_rows(engine)) == 1


def test_screen_records_exactly_one_failure_row_when_run_screen_itself_fails(tmp_path, raw_config, monkeypatch):
    cfg_path, settings, engine = _setup(tmp_path, raw_config, monkeypatch)
    monkeypatch.setattr(cli, "build_screen_provider", lambda *a, **k: FakeCandleProvider())

    def fake_run_screen(settings, engine, *a, **k):
        # Mirrors the real run_screen: it owns the job_runs row for "screen" itself.
        run_id = start_job_run(engine, "screen", datetime(2026, 9, 14, tzinfo=IST))
        finish_job_run(engine, run_id, datetime(2026, 9, 14, tzinfo=IST), error="factor computation blew up")
        raise RuntimeError("factor computation blew up")

    monkeypatch.setattr(cli, "run_screen", fake_run_screen)
    assert cli.main(["--config", str(cfg_path), "screen", "--date", "2026-09-14"]) == 1
    assert len(_failed_screen_rows(engine)) == 1


class FakeQuoteProvider:
    def get_quotes(self, symbols):
        return {s: 100.0 for s in symbols}


def test_preopen_records_exactly_one_failure_row_for_pre_annotate_failure(tmp_path, raw_config, monkeypatch):
    cfg_path, settings, engine = _setup(tmp_path, raw_config, monkeypatch)
    with engine.begin() as conn:
        conn.execute(insert(shortlist).values(
            trade_date="2026-09-14", rank=1, symbol="SBIN", composite_score=80.0,
            factor_scores_json='{"direction": "long"}', reasons="ok", demoted=0))

    monkeypatch.setattr(cli, "build_fyers_quote_provider", lambda *a, **k: FakeQuoteProvider())

    def boom(*a, **k):
        raise RuntimeError("cache disk full")

    monkeypatch.setattr(cli, "CandleCache", boom)
    assert cli.main(["--config", str(cfg_path), "preopen", "--date", "2026-09-14"]) == 1
    assert len(_failed_preopen_rows(engine)) == 1


def test_preopen_records_exactly_one_failure_row_when_annotate_preopen_itself_fails(tmp_path, raw_config,
                                                                                     monkeypatch):
    cfg_path, settings, engine = _setup(tmp_path, raw_config, monkeypatch)
    with engine.begin() as conn:
        conn.execute(insert(shortlist).values(
            trade_date="2026-09-14", rank=1, symbol="SBIN", composite_score=80.0,
            factor_scores_json='{"direction": "long"}', reasons="ok", demoted=0))

    monkeypatch.setattr(cli, "build_fyers_quote_provider", lambda *a, **k: FakeQuoteProvider())

    def fake_annotate_preopen(engine, trade_date, quotes, prev_close, daily_atr, max_gap_atr, oppose_gap_atr, now):
        # Mirrors the real annotate_preopen: it owns the job_runs row for "preopen" itself.
        run_id = start_job_run(engine, "preopen", now)
        finish_job_run(engine, run_id, now, error="db write blew up")
        raise RuntimeError("db write blew up")

    monkeypatch.setattr(cli, "annotate_preopen", fake_annotate_preopen)
    assert cli.main(["--config", str(cfg_path), "preopen", "--date", "2026-09-14"]) == 1
    assert len(_failed_preopen_rows(engine)) == 1


def test_preopen_skips_without_shortlist(tmp_path, raw_config, monkeypatch, capsys):
    cfg_path, settings, engine = _setup(tmp_path, raw_config, monkeypatch)
    assert cli.main(["--config", str(cfg_path), "preopen", "--date", "2026-09-14"]) == 0
    assert "no shortlist" in capsys.readouterr().out


def test_preopen_skips_and_warns_when_fyers_unavailable(tmp_path, raw_config, monkeypatch):
    cfg_path, settings, engine = _setup(tmp_path, raw_config, monkeypatch)
    with engine.begin() as conn:
        conn.execute(insert(shortlist).values(
            trade_date="2026-09-14", rank=1, symbol="SBIN", composite_score=80.0,
            factor_scores_json='{"direction": "long"}', reasons="ok", demoted=0))

    def boom(*a, **k):
        raise RuntimeError("token expired")

    monkeypatch.setattr(cli, "build_fyers_quote_provider", boom)
    assert cli.main(["--config", str(cfg_path), "preopen", "--date", "2026-09-14"]) == 0

    from tradalgo.storage.schema import health_events
    with engine.connect() as conn:
        rows = conn.execute(select(health_events.c.component, health_events.c.message)).all()
    assert any(r.component == "data" and "token expired" in r.message for r in rows)


def test_dashboard_invokes_streamlit_with_configured_host_port(tmp_path, raw_config, monkeypatch):
    cfg_path, settings, engine = _setup(tmp_path, raw_config, monkeypatch)
    calls = []

    class Result:
        returncode = 0

    def fake_run(cmd, env=None):
        calls.append(cmd)
        return Result()

    monkeypatch.setattr(cli, "run_subprocess", fake_run)
    assert cli.main(["--config", str(cfg_path), "dashboard"]) == 0
    # launchd gives the job no venv on PATH: the dashboard must run through this interpreter
    assert calls[0][:3] == [sys.executable, "-m", "streamlit"]
    assert calls[0][3] == "run" and Path(calls[0][4]).is_absolute() and Path(calls[0][4]).exists()
    assert "127.0.0.1" in calls[0]
    assert "8501" in calls[0]


def test_install_launchd_dry_run_prints_plists(tmp_path, raw_config, monkeypatch, capsys):
    cfg_path, settings, engine = _setup(tmp_path, raw_config, monkeypatch)
    assert cli.main(["--config", str(cfg_path), "install-launchd", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "com.tradalgo.screen.plist" in out
    assert "launchctl bootstrap" in out
    assert "pmset repeat wakeorpoweron" in out


def test_install_launchd_writes_files(tmp_path, raw_config, monkeypatch):
    cfg_path, settings, engine = _setup(tmp_path, raw_config, monkeypatch)
    dest = tmp_path / "LaunchAgents"
    assert cli.main(["--config", str(cfg_path), "install-launchd", "--dest", str(dest)]) == 0
    assert (dest / "com.tradalgo.screen.plist").exists()
    assert (dest / "com.tradalgo.worker.plist").exists()


def test_backtest_cli_defaults_capital_and_risk_from_settings(tmp_path, raw_config, monkeypatch):
    """I2: the M6 gate must validate the risk configuration that will actually run live."""
    cfg_path, settings, engine = _setup(tmp_path, raw_config, monkeypatch)
    seen = {}
    monkeypatch.setattr(cli, "validate_backtest_params_hook", None, raising=False)

    from tradalgo.dashboard import controls

    def fake_validate(params):
        seen.update(params)
        raise ValueError("stop here")

    monkeypatch.setattr(controls, "validate_backtest_params", fake_validate)
    assert cli.main(["--config", str(cfg_path), "backtest", "--from", "2026-01-01", "--to", "2026-02-01"]) == 1
    assert seen["max_risk_pct"] == settings.capital.max_risk_pct
    assert seen["initial_capital"] == settings.capital.initial_capital
