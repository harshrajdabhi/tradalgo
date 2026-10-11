"""Shapes the React app depends on (found by the real-API e2e run, which the mock run cannot catch)."""
import pytest
from fastapi.testclient import TestClient

from tests.test_api_helpers import make_seeded_config
from tradalgo.api.app import create_app


@pytest.fixture
def seeded(tmp_path):
    config_path, ids = make_seeded_config(tmp_path)
    return TestClient(create_app(str(config_path))), ids


@pytest.mark.parametrize("path", ["/api/shortlist", "/api/signals"])
def test_date_defaults_to_today(seeded, path):
    client, _ = seeded
    r = client.get(path)
    assert r.status_code == 200
    assert r.json() == []  # seed data is on 2026-09-10, not today


def test_detail_diagnostics_use_ui_shapes(seeded):
    client, ids = seeded
    diag = client.get(f"/api/backtests/{ids['run_id']}").json()["diagnostics"]
    assert diag["by_hour"] == [{"hour": 9, "trades": 1, "avg_r": 1.9}]
    assert diag["by_exit_reason"] == [{"reason": "target", "count": 1, "share": 1.0}]
    assert diag["mfe_losers_by_strategy"] == {}
    assert diag["rejections"] == []
    assert diag["overall"]["trades"] == 1  # raw keys are kept
