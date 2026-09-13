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
