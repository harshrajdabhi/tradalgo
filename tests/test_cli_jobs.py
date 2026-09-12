from datetime import date, datetime

import yaml
from sqlalchemy import insert, select

from tradalgo import cli
from tradalgo.clock import IST, FixedClock
from tradalgo.data.base import empty_candles
from tradalgo.storage.db import init_db, make_engine
from tradalgo.storage.repo import finish_job_run, has_job_succeeded_on, start_job_run
from tradalgo.storage.schema import alerts, shortlist


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
    assert calls[0][:2] == ["streamlit", "run"]
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
