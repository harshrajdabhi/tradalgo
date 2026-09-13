import json

import pytest
from sqlalchemy import insert

from tradalgo.backtest.diagnostics import _reason_category, diagnose, load_run, render_markdown
from tradalgo.cli import main
from tradalgo.storage.db import init_db, make_engine
from tradalgo.storage.schema import backtest_runs, backtest_trades, decisions, signals


@pytest.fixture
def engine(tmp_path):
    eng = make_engine(tmp_path / "t.db")
    init_db(eng)
    return eng


def _signal(conn, *, strategy, direction, regime, backtest_run_id):
    return conn.execute(insert(signals).values(
        ts="2026-03-02T09:30:00+05:30", symbol="AAA", strategy=strategy, direction=direction,
        regime=regime, market_regime="trend_up", entry=100.0, stop_loss=99.0, target_2r=102.0,
        target_3r=103.0, features_json="{}", mode="backtest", backtest_run_id=backtest_run_id,
    )).inserted_primary_key[0]


def seed_run(engine) -> int:
    with engine.begin() as conn:
        # expectancy_r_no_slippage (-0.05) is deliberately different from the rows' net_r mean
        # (0.2 / 3 = 0.0667): backtest_trades has no net_r_no_slippage column, so the stored
        # metrics_json value is the only correct source for it.
        run_id = conn.execute(insert(backtest_runs).values(
            created_at="2026-09-12T00:00:00+05:30", status="done", params_json="{}",
            metrics_json=json.dumps({
                "trades": 3, "win_rate": 0.3333, "expectancy_r": 0.0667,
                "expectancy_r_no_slippage": -0.05, "profit_factor": 1.15, "max_drawdown_r": 1.0,
                "net_r": 0.2, "net_rupees": 123.45, "missed_entries": 1, "fill_rate": 0.75,
                "missed": [
                    {"signal_id": 999, "trade_date": "2026-03-03", "symbol": "BBB", "strategy": "orb",
                     "direction": "long", "next_open": 101.0, "limit_low": 100.0, "limit_high": 100.5},
                ],
            }),
        )).inserted_primary_key[0]

        # orb winner: exits via runner_exit, mfe well past 1R -> not a "losers never reach 0.5R" case.
        sig_win = _signal(conn, strategy="orb", direction="long", regime="trend_up", backtest_run_id=run_id)
        conn.execute(insert(decisions).values(signal_id=sig_win, accepted=1, qty=10, leverage_used=1.0,
                                              risk_rupees=100.0, est_cost=20.0, expected_value_r=0.5,
                                              room_to_target_r=2.0))
        conn.execute(insert(backtest_trades).values(
            backtest_run_id=run_id, signal_id=sig_win, trade_date="2026-03-02", symbol="AAA",
            strategy="orb", direction="long", entry_ts="2026-03-02T09:30:00+05:30", entry_price=100.0,
            exit_ts="2026-03-02T10:15:00+05:30", exit_price=103.0, exit_reason="runner_exit", qty=10,
            mfe_r=1.6, mae_r=-0.1, gross_r=1.6, net_r=1.5,
        ))

        # orb loser: stopped out, mfe never reached 0.5R -> entry-quality evidence.
        sig_loss = _signal(conn, strategy="orb", direction="long", regime="trend_up", backtest_run_id=run_id)
        conn.execute(insert(decisions).values(signal_id=sig_loss, accepted=1, qty=10, leverage_used=1.0,
                                              risk_rupees=100.0, est_cost=20.0, expected_value_r=0.5,
                                              room_to_target_r=2.0))
        conn.execute(insert(backtest_trades).values(
            backtest_run_id=run_id, signal_id=sig_loss, trade_date="2026-03-02", symbol="AAA",
            strategy="orb", direction="long", entry_ts="2026-03-02T09:30:00+05:30", entry_price=100.0,
            exit_ts="2026-03-02T09:45:00+05:30", exit_price=99.0, exit_reason="stop_hit", qty=10,
            mfe_r=0.2, mae_r=-1.0, gross_r=-0.9, net_r=-1.0,
        ))

        # vwap trade: exits via hard_exit at a small loss, at 14:00 IST, short, range regime.
        sig_vwap = _signal(conn, strategy="vwap", direction="short", regime="range", backtest_run_id=run_id)
        conn.execute(insert(decisions).values(signal_id=sig_vwap, accepted=1, qty=5, leverage_used=1.0,
                                              risk_rupees=50.0, est_cost=10.0, expected_value_r=0.2,
                                              room_to_target_r=1.0))
        conn.execute(insert(backtest_trades).values(
            backtest_run_id=run_id, signal_id=sig_vwap, trade_date="2026-03-02", symbol="AAA",
            strategy="vwap", direction="short", entry_ts="2026-03-02T14:00:00+05:30", entry_price=100.0,
            exit_ts="2026-03-02T15:00:00+05:30", exit_price=100.3, exit_reason="hard_exit", qty=5,
            mfe_r=1.2, mae_r=-0.5, gross_r=-0.2, net_r=-0.3,
        ))

        # rejected signals: not turned into trades at all.
        sig_rej1 = _signal(conn, strategy="gap", direction="long", regime="trend_up", backtest_run_id=run_id)
        conn.execute(insert(decisions).values(signal_id=sig_rej1, accepted=0, rejection_reason="low_room"))
        sig_rej2 = _signal(conn, strategy="orb", direction="long", regime="trend_up", backtest_run_id=run_id)
        conn.execute(insert(decisions).values(signal_id=sig_rej2, accepted=0, rejection_reason="cost_r"))
        sig_rej3 = _signal(conn, strategy="gap", direction="long", regime="trend_up", backtest_run_id=run_id)
        conn.execute(insert(decisions).values(signal_id=sig_rej3, accepted=0, rejection_reason="low_room"))

    return run_id


def test_load_run_joins_regime_and_metrics(engine):
    run_id = seed_run(engine)
    run = load_run(engine, run_id)
    assert len(run.trades) == 3
    assert set(run.trades["strategy"]) == {"orb", "vwap"}
    assert set(run.trades.loc[run.trades["strategy"] == "orb", "regime"]) == {"trend_up"}
    assert run.metrics["missed"][0]["strategy"] == "orb"
    assert len(run.decisions) == 6


def test_load_run_missing_run_raises(engine):
    with pytest.raises(ValueError):
        load_run(engine, 999)


def test_diagnose_by_strategy_and_drag(engine):
    run = load_run(engine, seed_run(engine))
    report = diagnose(run)

    orb = report["by_strategy"]["orb"]
    assert orb["trades"] == 2
    assert orb["win_rate"] == pytest.approx(0.5)
    assert orb["expectancy_r"] == pytest.approx((1.5 - 1.0) / 2)
    assert orb["avg_cost_slippage_drag_r"] == pytest.approx(((1.6 - 1.5) + (-0.9 - -1.0)) / 2)

    vwap = report["by_strategy"]["vwap"]
    assert vwap["trades"] == 1
    assert vwap["win_rate"] == 0.0


def test_diagnose_by_regime_direction_exit_reason(engine):
    report = diagnose(load_run(engine, seed_run(engine)))
    assert report["by_regime"]["trend_up"]["trades"] == 2
    assert report["by_regime"]["range"]["trades"] == 1
    assert report["by_direction"]["long"]["trades"] == 2
    assert report["by_direction"]["short"]["trades"] == 1
    assert report["by_exit_reason"]["stop_hit"]["trades"] == 1
    assert report["by_exit_reason"]["hard_exit"]["trades"] == 1
    assert report["by_exit_reason"]["runner_exit"]["trades"] == 1


def test_mfe_buckets_for_losers(engine):
    report = diagnose(load_run(engine, seed_run(engine)))
    orb_losers = report["mfe_losers_by_strategy"]["orb"]
    assert orb_losers["count"] == 1
    assert orb_losers["pct_ge_0_5r"] == 0.0
    assert orb_losers["pct_ge_1r"] == 0.0

    vwap_losers = report["mfe_losers_by_strategy"]["vwap"]
    assert vwap_losers["count"] == 1
    assert vwap_losers["pct_ge_0_5r"] == 1.0
    assert vwap_losers["pct_ge_1r"] == 1.0
    assert vwap_losers["pct_ge_2r"] == 0.0


def test_hard_exit_by_strategy(engine):
    report = diagnose(load_run(engine, seed_run(engine)))
    assert report["hard_exit_by_strategy"]["vwap"] == {"count": 1, "avg_net_r": -0.3}
    assert "orb" not in report["hard_exit_by_strategy"]


def test_fill_rate_by_strategy(engine):
    report = diagnose(load_run(engine, seed_run(engine)))
    orb_fill = report["fill_rate_by_strategy"]["orb"]
    assert orb_fill == {"trades": 2, "missed": 1, "fill_rate": round(2 / 3, 4)}
    vwap_fill = report["fill_rate_by_strategy"]["vwap"]
    assert vwap_fill == {"trades": 1, "missed": 0, "fill_rate": 1.0}


def test_rejections_by_strategy_and_reason(engine):
    report = diagnose(load_run(engine, seed_run(engine)))
    assert report["rejections"]["gap"]["low_room"] == 2
    assert report["rejections"]["orb"]["cost_r"] == 1


def test_overall_takes_expectancy_r_no_slippage_from_stored_metrics_json(engine):
    run = load_run(engine, seed_run(engine))
    net_r_mean = round(run.trades["net_r"].mean(), 4)
    report = diagnose(run)
    # the stored value differs from what recomputing off backtest_trades' net_r would give -
    # asserting against net_r_mean pins down that the bug (silently falling back to net_r) is fixed.
    assert report["overall"]["expectancy_r_no_slippage"] == -0.05
    assert report["overall"]["expectancy_r_no_slippage"] != net_r_mean
    assert report["overall"]["trades"] == 3
    assert report["overall"]["net_rupees"] == 123.45


def test_overall_falls_back_and_omits_no_slippage_without_metrics_json(engine):
    run_id = seed_run(engine)
    run = load_run(engine, run_id)
    run.metrics = {}  # simulate an old/blank metrics_json
    report = diagnose(run)
    assert report["overall"]["trades"] == 3
    assert report["overall"]["expectancy_r"] == round(run.trades["net_r"].mean(), 4)
    assert "expectancy_r_no_slippage" not in report["overall"]
    assert "net_rupees" not in report["overall"]


def test_render_markdown_shows_stored_no_slippage_value(engine):
    report = diagnose(load_run(engine, seed_run(engine)))
    md = render_markdown(report)
    assert "-0.0500" in md


@pytest.mark.parametrize("reason,expected", [
    ("insufficient room: level 5713.0 is 0.39R away (< 2.0R)", "insufficient room"),
    ("qty is 0 (capital 10926.69, risk/share 150.00, leverage 3.0)", "qty is #"),
    ("expected value -0.021R <= 0 after costs", "expected value #R <= # after costs"),
    ("not independent: same symbol ABB already traded today", "not independent"),
    ("max trades per day reached (2/2)", "max trades per day reached"),
    ("after a -1R loss on PNB/gap, second trade needs a different strategy",
     "after a #R loss on <symbol/strategy>, second trade needs a different strategy"),
])
def test_reason_category_collapses_variable_detail(reason, expected):
    assert _reason_category(reason) == expected


def test_render_markdown_has_key_sections(engine):
    report = diagnose(load_run(engine, seed_run(engine)))
    md = render_markdown(report)
    for heading in ("## Overall", "By strategy", "By regime", "By hour of entry", "By direction",
                    "By exit reason", "MFE analysis: losing trades",
                    "Winners that exited via stop_hit after a partial", "Hard-exit trades by strategy",
                    "Fill rate by strategy", "Rejected signals by strategy x reason",
                    "## What the numbers suggest"):
        assert heading in md
    assert "orb" in md and "vwap" in md


def test_render_markdown_flags_entry_quality_for_low_mfe(engine):
    report = diagnose(load_run(engine, seed_run(engine)))
    md = render_markdown(report)
    assert "orb" in md.split("## What the numbers suggest")[1]


def test_cli_diagnose_writes_report(engine, tmp_path, monkeypatch):
    run_id = seed_run(engine)
    db_path = str(engine.url).replace("sqlite:///", "")
    config = tmp_path / "config.yaml"
    config.write_text(f"paths:\n  data_dir: {tmp_path}\n  db_path: {db_path}\n")

    monkeypatch.setattr("tradalgo.cli.load_settings", lambda path: _fake_settings(db_path))
    out_dir = tmp_path / "reports"
    rc = main(["diagnose", "--run-id", str(run_id), "--out", str(out_dir)])
    assert rc == 0
    report_path = out_dir / f"diagnostics-run{run_id}.md"
    assert report_path.exists()
    assert "## Overall" in report_path.read_text()


def test_cli_diagnose_missing_run_exits_1(engine, tmp_path, monkeypatch):
    db_path = str(engine.url).replace("sqlite:///", "")
    monkeypatch.setattr("tradalgo.cli.load_settings", lambda path: _fake_settings(db_path))
    rc = main(["diagnose", "--run-id", "12345", "--out", str(tmp_path / "reports")])
    assert rc == 1


class _FakePaths:
    def __init__(self, db_path):
        self.db_path = db_path


class _FakeSettings:
    def __init__(self, db_path):
        self.paths = _FakePaths(db_path)


def _fake_settings(db_path):
    return _FakeSettings(db_path)
