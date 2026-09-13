import json
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from tradalgo.api.app import create_app
from tests.test_api_helpers import make_empty_config, make_seeded_config


@pytest.fixture
def empty_client(tmp_path):
    config_path = make_empty_config(tmp_path)
    app = create_app(str(config_path))
    return TestClient(app)


@pytest.fixture
def seeded(tmp_path):
    config_path, ids = make_seeded_config(tmp_path)
    app = create_app(str(config_path))
    return TestClient(app), ids


@pytest.fixture
def seeded_cfg(tmp_path):
    """Like `seeded`, but also hands back the config path so a test can reach the DB directly
    (e.g. to simulate a not-yet-migrated column via a raw ALTER TABLE)."""
    config_path, ids = make_seeded_config(tmp_path)
    app = create_app(str(config_path))
    return TestClient(app), ids, config_path


def test_health_empty(empty_client):
    r = empty_client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["kill_switch"] is False


def test_now_empty_is_quiet(empty_client):
    r = empty_client.get("/api/now")
    assert r.status_code == 200
    assert r.json()["quiet"] is True


def test_now_seeded_priority_is_failed_alert(seeded):
    client, ids = seeded
    r = client.get("/api/now", params={"date": "2026-09-10"})
    body = r.json()
    assert body["quiet"] is False
    assert "failed to send" in body["headline"]
    assert "<" not in body["headline"] and ">" not in body["headline"]


def test_shortlist(empty_client, seeded):
    assert empty_client.get("/api/shortlist", params={"date": "2026-09-10"}).json() == []
    client, _ = seeded
    r = client.get("/api/shortlist", params={"date": "2026-09-10"})
    assert r.json()[0]["symbol"] == "RELIANCE"


def test_signals(seeded):
    client, _ = seeded
    r = client.get("/api/signals", params={"date": "2026-09-10"})
    assert r.json()[0]["accepted"] == 1


def test_positions_awaiting_reply_flag(empty_client, seeded):
    assert empty_client.get("/api/positions").json() == []
    client, _ = seeded
    r = client.get("/api/positions")
    row = r.json()[0]
    assert row["net_r"] == 1.9
    assert "awaiting_reply" in row


def test_alerts_counts(seeded):
    client, _ = seeded
    r = client.get("/api/alerts")
    body = r.json()
    assert body["counts"]["failed"] == 1
    r2 = client.get("/api/alerts", params={"status": "failed"})
    assert len(r2.json()["alerts"]) == 1


def test_journal(seeded):
    client, _ = seeded
    r = client.get("/api/journal", params={"from": "2026-09-01", "to": "2026-09-30"})
    assert len(r.json()) == 1


def test_analytics(empty_client, seeded):
    r = empty_client.get("/api/analytics")
    assert r.json()["expectancy_by_strategy"] == []
    client, _ = seeded
    r2 = client.get("/api/analytics")
    assert r2.json()["expectancy_by_strategy"][0]["grp"] == "orb"


def test_jobs(seeded):
    client, _ = seeded
    r = client.get("/api/jobs")
    body = r.json()
    assert body["job_runs"][0]["job"] == "screen"
    assert len(body["degraded_data"]) == 1


def test_backtests_list_and_detail(seeded):
    client, ids = seeded
    run_id = ids["run_id"]
    r = client.get("/api/backtests")
    assert r.json()[0]["id"] == run_id
    r2 = client.get(f"/api/backtests/{run_id}")
    body = r2.json()
    assert body["metrics"]["trades"] == 1
    assert body["gate"]["passed"] is False  # only 1 trade, needs >= 100
    assert body["diagnostics"]["overall"]["trades"] == 1


def test_backtests_detail_missing_404(empty_client):
    assert empty_client.get("/api/backtests/999").status_code == 404


def test_create_backtest_valid(empty_client):
    params = {
        "from": "2026-01-01", "to": "2026-06-30", "universe": "nifty50",
        "strategies": ["orb"], "shortlist_size": 6, "slippage_pct": 0.05,
        "max_risk_pct": 0.02, "initial_capital": 20000,
    }
    r = empty_client.post("/api/backtests", json=params)
    assert r.status_code == 201
    assert "id" in r.json()


def test_create_backtest_invalid_422(empty_client):
    params = {
        "from": "2026-01-01", "to": "2026-06-30", "universe": "bogus",
        "strategies": ["orb"], "shortlist_size": 6, "slippage_pct": 0.05,
        "max_risk_pct": 0.02, "initial_capital": 20000,
    }
    r = empty_client.post("/api/backtests", json=params)
    assert r.status_code == 422


def test_cancel_backtest(empty_client):
    params = {
        "from": "2026-01-01", "to": "2026-06-30", "universe": "nifty50",
        "strategies": ["orb"], "shortlist_size": 6, "slippage_pct": 0.05,
        "max_risk_pct": 0.02, "initial_capital": 20000,
    }
    run_id = empty_client.post("/api/backtests", json=params).json()["id"]
    r = empty_client.post(f"/api/backtests/{run_id}/cancel")
    assert r.status_code == 200


def test_backtest_live_equity_curve(seeded):
    client, ids = seeded
    r = client.get(f"/api/backtests/{ids['run_id']}/live")
    body = r.json()
    assert body["trades_so_far"] == 1
    assert body["equity_curve"] == [{"trade_index": 1, "exit_ts": "2026-09-10T09:30:00+05:30", "cum_net_r": 1.9}]
    assert body["by_strategy"][0]["strategy"] == "orb"


def test_backtest_live_empty(empty_client):
    r = empty_client.get("/api/backtests/1/live")
    assert r.status_code == 404


def test_backtest_trades_filters(seeded):
    client, ids = seeded
    run_id = ids["run_id"]
    assert len(client.get(f"/api/backtests/{run_id}/trades").json()) == 1
    assert len(client.get(f"/api/backtests/{run_id}/trades", params={"strategy": "gap"}).json()) == 0
    assert len(client.get(f"/api/backtests/{run_id}/trades", params={"outcome": "win"}).json()) == 1
    assert len(client.get(f"/api/backtests/{run_id}/trades", params={"outcome": "loss"}).json()) == 0


def test_trade_replay_no_cache(seeded):
    client, ids = seeded
    r = client.get(f"/api/backtests/{ids['run_id']}/trades/{ids['trade_id']}/replay")
    assert r.status_code == 200
    body = r.json()
    assert body["candles"] == []
    assert body["levels"]["stop"] == 98.0
    assert body["markers"][0]["kind"] == "entry"


def test_trade_replay_with_cached_candles(tmp_path):
    import pandas as pd
    from tradalgo.data.candle_cache import CandleCache

    config_path, ids = make_seeded_config(tmp_path)
    with open(config_path) as f:
        cfg = yaml.safe_load(f)
    data_dir = cfg["paths"]["data_dir"]

    idx = pd.date_range("2026-09-10 09:15", periods=3, freq="5min", tz="Asia/Kolkata")
    df = pd.DataFrame({"open": [100, 101, 102], "high": [101, 102, 103], "low": [99, 100, 101],
                       "close": [100.5, 101.5, 102.5], "volume": [1000, 1000, 1000]}, index=idx)
    df.index.name = "timestamp"
    cache_dir = f"{data_dir}/candles"
    (cache := CandleCache(cache_dir, provider=None))
    path = cache._path("RELIANCE", "5m")
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path)

    app = create_app(str(config_path))
    client = TestClient(app)
    r = client.get(f"/api/backtests/{ids['run_id']}/trades/{ids['trade_id']}/replay")
    body = r.json()
    assert len(body["candles"]) == 3
    assert body["candles"][0]["open"] == 100.0
    assert len(body["session_vwap"]) == 3


def test_candles_endpoint(seeded):
    client, _ = seeded
    r = client.get("/api/candles/RELIANCE", params={"date": "2026-09-10"})
    assert r.status_code == 200
    body = r.json()
    assert body["candles"] == []
    assert body["levels"]["entry"] == 100.0


def test_resend_alert_only_from_failed(seeded):
    client, ids = seeded
    r = client.post(f"/api/alerts/{ids['alert_id']}/resend")
    assert r.status_code == 200
    r2 = client.post(f"/api/alerts/{ids['alert_id']}/resend")
    assert r2.status_code == 409


def test_kill_switch_toggles_file(empty_client, tmp_path):
    r = empty_client.post("/api/kill-switch", json={"on": True})
    assert r.status_code == 200
    assert empty_client.get("/api/health").json()["kill_switch"] is True
    empty_client.post("/api/kill-switch", json={"on": False})
    assert empty_client.get("/api/health").json()["kill_switch"] is False


def test_settings_get_and_put(empty_client):
    current = empty_client.get("/api/settings").json()
    assert "capital" in current
    new_config = dict(current)
    new_config["capital"] = dict(current["capital"], initial_capital=30000)
    r = empty_client.put("/api/settings", json=new_config)
    assert r.status_code == 200
    assert r.json()["backup"] is not None
    assert empty_client.get("/api/settings").json()["capital"]["initial_capital"] == 30000


def test_settings_put_invalid_422_and_file_untouched(tmp_path):
    config_path = make_empty_config(tmp_path)
    app = create_app(str(config_path))
    client = TestClient(app)
    before = config_path.read_text()

    current = client.get("/api/settings").json()
    bad = dict(current)
    bad["capital"] = dict(current["capital"], max_risk_pct=1.0)
    r = client.put("/api/settings", json=bad)
    assert r.status_code == 422
    assert config_path.read_text() == before


def test_sweeps_empty(empty_client):
    assert empty_client.get("/api/sweeps").json() == []


def test_sweeps_path_traversal_rejected(empty_client):
    r = empty_client.get("/api/sweeps/..%2F..%2Fetc%2Fpasswd")
    assert r.status_code in (400, 404)
    r2 = empty_client.get("/api/sweeps/not-a-sweep-name")
    assert r2.status_code == 400


def test_sweeps_list_and_get(tmp_path):
    config_path = make_empty_config(tmp_path)
    with open(config_path) as f:
        cfg = yaml.safe_load(f)
    reports_dir = Path(cfg["paths"]["data_dir"]) / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    payload = {"generated_at": "2026-09-14T00:00:00+05:30", "verdict": "no", "total_combinations": 2}
    (reports_dir / "sweep-20260914-000000.json").write_text(json.dumps(payload))
    (reports_dir / "sweep-20260914-000000-recommended.yaml").write_text("foo: 1\n")

    app = create_app(str(config_path))
    client = TestClient(app)
    r = client.get("/api/sweeps")
    assert len(r.json()) == 1
    r2 = client.get("/api/sweeps/sweep-20260914-000000")
    assert r2.status_code == 200
    assert "recommended_yaml" in r2.json()


# ---- Fix round 1: symbol validation ------------------------------------------------------------

@pytest.mark.parametrize("bad_symbol", ["../x", "..%2Fx", "reliance", "A" * 21])
def test_candles_rejects_invalid_symbol(empty_client, bad_symbol):
    r = empty_client.get(f"/api/candles/{bad_symbol}", params={"date": "2026-09-10"})
    assert r.status_code == 404


@pytest.mark.parametrize("good_symbol", ["M&M", "BAJAJ-AUTO"])
def test_candles_accepts_valid_symbol(empty_client, good_symbol):
    r = empty_client.get(f"/api/candles/{good_symbol}", params={"date": "2026-09-10"})
    assert r.status_code == 200
    assert r.json()["candles"] == []


def test_trade_replay_rejects_invalid_symbol(seeded_cfg):
    import sqlalchemy as sa

    client, ids, config_path = seeded_cfg
    with open(config_path) as f:
        cfg = yaml.safe_load(f)
    engine = sa.create_engine(f"sqlite:///{cfg['paths']['data_dir']}/tradalgo.db")
    with engine.begin() as conn:
        conn.execute(sa.text("UPDATE backtest_trades SET symbol = '../x' WHERE id = :id"),
                    {"id": ids["trade_id"]})
    engine.dispose()

    r = client.get(f"/api/backtests/{ids['run_id']}/trades/{ids['trade_id']}/replay")
    assert r.status_code == 404


# ---- Fix round 1: SPA fallback with a tmp web/dist -----------------------------------------

@pytest.fixture
def spa_client(tmp_path):
    config_path = make_empty_config(tmp_path)
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html><body>spa shell</body></html>")
    (dist / "assets" / "app.js").write_text("console.log('hi')")
    app = create_app(str(config_path), web_dist=str(dist))
    return TestClient(app)


def test_spa_serves_index_at_root(spa_client):
    r = spa_client.get("/")
    assert r.status_code == 200
    assert "spa shell" in r.text


def test_spa_serves_index_for_client_route(spa_client):
    r = spa_client.get("/backtests/5")
    assert r.status_code == 200
    assert "spa shell" in r.text


def test_spa_serves_real_asset(spa_client):
    r = spa_client.get("/assets/app.js")
    assert r.status_code == 200
    assert "console.log" in r.text


def test_spa_unknown_api_route_is_json_404(spa_client):
    r = spa_client.get("/api/unknown")
    assert r.status_code == 404
    assert r.json() == {"detail": "not found"}


# ---- Fix round 1: legs_json-driven replay markers + stop_path ------------------------------

def _add_legs_json_column(config_path):
    """Ensures `backtest_trades.legs_json` exists, whether or not the schema migration (owned by
    another agent) has landed yet in this checkout — the API must work either way.
    """
    import sqlalchemy as sa

    with open(config_path) as f:
        cfg = yaml.safe_load(f)
    engine = sa.create_engine(f"sqlite:///{cfg['paths']['data_dir']}/tradalgo.db")
    existing = {c["name"] for c in sa.inspect(engine).get_columns("backtest_trades")}
    if "legs_json" not in existing:
        with engine.begin() as conn:
            conn.execute(sa.text("ALTER TABLE backtest_trades ADD COLUMN legs_json TEXT"))
    return engine


def test_trade_replay_uses_legs_json_when_present(seeded_cfg):
    import sqlalchemy as sa

    client, ids, config_path = seeded_cfg
    engine = _add_legs_json_column(config_path)
    legs = [
        {"kind": "partial_exit", "ts": "2026-09-10T09:35:00+05:30", "price": 102.0, "qty": 5, "r": 1.0},
        {"kind": "trail_update", "ts": "2026-09-10T09:40:00+05:30", "price": None, "qty": 0, "r": 0.0,
         "new_stop": 100.0},
        {"kind": "stop_hit", "ts": "2026-09-10T09:45:00+05:30", "price": 100.0, "qty": 5, "r": 0.5},
    ]
    with engine.begin() as conn:
        conn.execute(sa.text("UPDATE backtest_trades SET legs_json = :legs WHERE id = :id"),
                    {"legs": json.dumps(legs), "id": ids["trade_id"]})
    engine.dispose()

    r = client.get(f"/api/backtests/{ids['run_id']}/trades/{ids['trade_id']}/replay")
    assert r.status_code == 200
    body = r.json()
    assert [m["kind"] for m in body["markers"]] == ["entry", "partial_exit", "trail_update", "stop_hit"]
    assert len(body["markers"]) == 4
    assert len(body["stop_path"]) == 2
    assert body["stop_path"][0]["value"] == 98.0  # the signal's stop, at entry
    assert body["stop_path"][1]["value"] == 100.0  # the trail_update's new_stop


def test_trade_replay_falls_back_when_legs_json_null(seeded_cfg):
    client, ids, config_path = seeded_cfg
    _add_legs_json_column(config_path).dispose()  # column exists but is NULL for this row

    r = client.get(f"/api/backtests/{ids['run_id']}/trades/{ids['trade_id']}/replay")
    assert r.status_code == 200
    body = r.json()
    assert [m["kind"] for m in body["markers"]] == ["entry", "runner_exit"]  # exit_reason="target"
    assert len(body["stop_path"]) == 1


def test_trade_replay_falls_back_when_column_missing(seeded):
    """No migration at all (today's schema): same fallback shape as the NULL case."""
    client, ids = seeded
    r = client.get(f"/api/backtests/{ids['run_id']}/trades/{ids['trade_id']}/replay")
    assert r.status_code == 200
    body = r.json()
    assert [m["kind"] for m in body["markers"]] == ["entry", "runner_exit"]
    assert len(body["stop_path"]) == 1
    assert body["stop_path"][0]["value"] == 98.0
