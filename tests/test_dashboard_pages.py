import json
from datetime import datetime
from pathlib import Path

import pytest
import yaml
from sqlalchemy import insert
from streamlit.testing.v1 import AppTest

from tradalgo.storage.db import init_db, make_engine
from tradalgo.storage.schema import (
    alerts, backtest_runs, backtest_trades, decisions, health_events, job_runs,
    paper_trades, shortlist, signals, user_actions,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PAGES_DIR = REPO_ROOT / "tradalgo" / "dashboard" / "pages"
PAGES = sorted(PAGES_DIR.glob("*.py"))
NOW = "2026-09-10T09:30:00+05:30"


def _write_config(tmp_path: Path) -> Path:
    config = yaml.safe_load((REPO_ROOT / "config.yaml").read_text())
    config["paths"]["data_dir"] = str(tmp_path / "data")
    config["paths"]["static_dir"] = str(REPO_ROOT / "data_static")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config))
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    return config_path


def _seed(db_path: Path) -> None:
    engine = make_engine(db_path)
    init_db(engine)
    with engine.begin() as conn:
        conn.execute(insert(shortlist).values(
            trade_date="2026-09-10", rank=1, symbol="RELIANCE", composite_score=0.8,
            factor_scores_json="{}", reasons="strong", gap_pct=1.2, demoted=0,
        ))
        sig_id = conn.execute(insert(signals).values(
            ts=NOW, symbol="RELIANCE", strategy="orb", direction="long", regime="trend",
            market_regime="trend", entry=100.0, stop_loss=98.0, target_2r=104.0, target_3r=106.0,
            features_json="{}", mode="live",
        )).inserted_primary_key[0]
        conn.execute(insert(decisions).values(
            signal_id=sig_id, accepted=1, qty=10, leverage_used=2.0, risk_rupees=200.0,
            est_cost=50.0, expected_value_r=0.5, room_to_target_r=3.0,
        ))
        alert_id = conn.execute(insert(alerts).values(
            dedup_key="d1", alert_type="entry", symbol="RELIANCE", signal_id=sig_id, text="go",
            status="failed", created_at=NOW, attempts=1, last_error="timeout",
        )).inserted_primary_key[0]
        conn.execute(insert(user_actions).values(alert_id=alert_id, action="taken", price=100.0, ts=NOW))
        conn.execute(insert(paper_trades).values(
            signal_id=sig_id, taken_by_user=1, entry_ts=NOW, entry_price=100.0, qty=10,
            exit_ts=NOW, exit_price=104.0, exit_reason="target", mfe_r=2.5, mae_r=-0.3,
            slippage_rupees=5.0, gross_r=2.0, net_r=1.9,
        ))
        run_id = conn.execute(insert(backtest_runs).values(
            created_at=NOW, status="done", params_json=json.dumps({"from": "2026-01-01"}),
            progress_pct=100, metrics_json=json.dumps({
                "trades": 1, "win_rate": 1.0, "expectancy_r": 1.9, "max_drawdown_r": 0.0,
                "by_strategy": {"orb": {"trades": 1, "win_rate": 1.0, "expectancy_r": 1.9}},
                "by_regime": {"trend": {"trades": 1, "win_rate": 1.0, "expectancy_r": 1.9}},
            }),
        )).inserted_primary_key[0]
        conn.execute(insert(backtest_trades).values(
            backtest_run_id=run_id, signal_id=sig_id, trade_date="2026-09-10", symbol="RELIANCE",
            strategy="orb", direction="long", entry_ts=NOW, entry_price=100.0, exit_ts=NOW,
            exit_price=104.0, exit_reason="target", qty=10, mfe_r=2.5, mae_r=-0.3, gross_r=2.0, net_r=1.9,
        ))
        conn.execute(insert(job_runs).values(
            job="screen", run_date="2026-09-10", started_at=NOW, finished_at=NOW, status="succeeded",
        ))
        conn.execute(insert(health_events).values(
            ts=NOW, component="data", level="warning", message="fallback used",
        ))


@pytest.mark.parametrize("page", PAGES, ids=[p.name for p in PAGES])
def test_page_renders_with_empty_db(page, tmp_path, monkeypatch):
    config_path = _write_config(tmp_path)
    engine = make_engine(tmp_path / "data" / "tradalgo.db")
    init_db(engine)
    monkeypatch.setenv("TRADALGO_CONFIG", str(config_path))

    at = AppTest.from_file(str(page))
    at.run(timeout=30)
    assert not at.exception


@pytest.mark.parametrize("page", PAGES, ids=[p.name for p in PAGES])
def test_page_renders_with_seeded_db(page, tmp_path, monkeypatch):
    config_path = _write_config(tmp_path)
    _seed(tmp_path / "data" / "tradalgo.db")
    monkeypatch.setenv("TRADALGO_CONFIG", str(config_path))

    at = AppTest.from_file(str(page))
    at.run(timeout=30)
    assert not at.exception


def test_now_strip_priority():
    from tradalgo.dashboard import theme

    # kill switch wins over everything else
    state = theme.now_strip_state(
        kill_switch_on=True, failed_alerts=[{"symbol": "X", "last_error": "e"}],
        awaiting_alerts=[{"symbol": "Y", "text": "t", "valid_until": "now"}],
        open_trades=[{"symbol": "Z", "entry_ts": "now"}], next_check="10:00",
    )
    assert "Resume alerts" in state.headline
    assert not state.quiet

    # failed alerts beat awaiting replies and open trades
    state = theme.now_strip_state(
        kill_switch_on=False, failed_alerts=[{"symbol": "X", "last_error": "timeout"}],
        awaiting_alerts=[{"symbol": "Y", "text": "t", "valid_until": "now"}],
        open_trades=[{"symbol": "Z", "entry_ts": "now"}], next_check="10:00",
    )
    assert "X" in state.headline and "timeout" in state.headline
    assert not state.quiet

    # awaiting replies beat open trades
    state = theme.now_strip_state(
        kill_switch_on=False, failed_alerts=[],
        awaiting_alerts=[{"symbol": "Y", "text": "buy Y", "valid_until": "10:30"}],
        open_trades=[{"symbol": "Z", "entry_ts": "now"}], next_check="10:00",
    )
    assert "Y" in state.headline and "10:30" in state.headline
    assert not state.quiet

    # open trades beat the quiet fallback
    state = theme.now_strip_state(
        kill_switch_on=False, failed_alerts=[], awaiting_alerts=[],
        open_trades=[{"symbol": "Z", "entry_ts": "09:20"}], next_check="10:00",
    )
    assert "Z" in state.headline
    assert not state.quiet

    # nothing to do: quiet state names the next check time
    state = theme.now_strip_state(
        kill_switch_on=False, failed_alerts=[], awaiting_alerts=[], open_trades=[],
        next_check="10:00",
    )
    assert "10:00" in state.headline
    assert state.quiet


def test_now_strip_html_escapes_dynamic_alert_text():
    """DB-sourced alert text / error strings must never inject markup into the Now strip."""
    from tradalgo.dashboard import theme

    state = theme.now_strip_state(
        kill_switch_on=False,
        failed_alerts=[{"symbol": "X", "last_error": "<script>alert(1)</script> timeout"}],
        awaiting_alerts=[], open_trades=[], next_check="10:00",
    )
    html_out = theme.render_now_strip_html(state)
    assert "<script>" not in html_out
    assert "timeout" in html_out

    state = theme.now_strip_state(
        kill_switch_on=False, failed_alerts=[],
        awaiting_alerts=[{"symbol": "Y", "text": "<b>Buy</b> RELIANCE &amp; hold", "valid_until": "10:30"}],
        open_trades=[], next_check="10:00",
    )
    html_out = theme.render_now_strip_html(state)
    assert "<b>" not in html_out
    assert "Buy RELIANCE" in html_out
    # the wrapper div itself is still real markup
    assert html_out.startswith('<div class="now-strip">')


def test_candlestick_amber_reserved_for_awaiting_reply():
    """Amber (theme.ACTION) must only color trade-level lines when the signal's entry
    alert is currently awaiting the user's reply; otherwise levels stay ink-toned.
    """
    import pandas as pd

    from tradalgo.dashboard import charts, theme

    candles = pd.DataFrame({
        "open": [1.0], "high": [2.0], "low": [0.5], "close": [1.5], "volume": [0.0],
    }, index=pd.to_datetime(["2026-09-10 09:15"]))

    fig_default = charts.candlestick_with_levels(candles, entry=1.0, stop_loss=0.8,
                                                  target_2r=1.4, target_3r=1.6)
    colors_default = {shape.line.color for shape in fig_default.layout.shapes}
    assert theme.ACTION not in colors_default
    assert colors_default <= {theme.INK, theme.INK_MUTED}

    fig_awaiting = charts.candlestick_with_levels(candles, entry=1.0, stop_loss=0.8,
                                                   target_2r=1.4, target_3r=1.6, awaiting_reply=True)
    colors_awaiting = {shape.line.color for shape in fig_awaiting.layout.shapes}
    assert colors_awaiting == {theme.ACTION}
