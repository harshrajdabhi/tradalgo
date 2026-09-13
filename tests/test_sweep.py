import json
from datetime import date, datetime, time

import pytest
import yaml
from sqlalchemy import func, select

from tradalgo import cli
from tradalgo.backtest import replay, sweep
from tradalgo.backtest.replay import MissingDataError
from tradalgo.backtest.sweep import ComboResult, Grid, SweepResult, expand_grid, run_sweep
from tradalgo.clock import IST
from tradalgo.storage.db import init_db, make_engine
from tradalgo.storage.schema import backtest_runs, backtest_trades, decisions, signals
from tradalgo.strategies.base import Signal
from tests.backtest_fixtures import REPLAY_DAYS, build_replay_cache, fake_classify, universe

TRAIN = (REPLAY_DAYS[0], REPLAY_DAYS[1])
TEST = (REPLAY_DAYS[2], REPLAY_DAYS[2])
SYMBOLS = universe(["AAA", "BBB", "CCC"])
# min_rvol -> (train stop distance, test stop distance); a wider stop scores higher here (runner caps R at 3)
STOPS = {1.5: (1.0, 1.0), 2.0: (5.0, 1.0), 3.0: (1.0, 5.0)}


def param_detector(ctx, settings, calendar):
    last = ctx.candles_5m.index[-1]
    if last.time() != time(9, 40):
        return []
    dist = STOPS[settings.strategies["orb"].params.get("min_rvol", 1.5)][0 if last.date() <= TRAIN[1] else 1]
    close = float(ctx.candles_5m["close"].iloc[-1])
    return [Signal(ctx.symbol, "orb", "long", last.to_pydatetime(), close, close - dist, ctx.regime,
                   ctx.market_regime, False, "fake", {})]


def rvol_grid(**kw) -> Grid:
    return Grid({"strategies": {"orb": {"params": {"min_rvol": [1.5, 2.0, 3.0]}}}}, **{"min_train_trades": 1, **kw})


def _sweep(settings, root, grid, workers=1):
    return run_sweep(settings, grid, TRAIN, TEST, workers, root, SYMBOLS, classify=fake_classify,
                     detect_all=param_detector)


@pytest.fixture(scope="module")
def cache_root(tmp_path_factory):
    root = tmp_path_factory.mktemp("candles")
    build_replay_cache(root)
    return root


def test_expand_full_product_and_scalar_leaves():
    total, combos = expand_grid(Grid({"a": {"x": [1, 2], "y": [True, False]}, "b": 5}))
    assert total == 4 and len(combos) == 4
    assert {"a": {"x": 2, "y": False}, "b": 5} in combos


def test_random_cap_is_seed_deterministic():
    grid = Grid({"a": list(range(10)), "b": list(range(10))}, max_combinations=7, seed=3)
    total, first = expand_grid(grid)
    assert total == 100 and len(first) == 7 and len({(c["a"], c["b"]) for c in first}) == 7
    assert expand_grid(grid)[1] == first
    assert expand_grid(Grid(grid.overrides, max_combinations=7, seed=4))[1] != first


def test_invalid_key_fails_before_running(settings, monkeypatch):
    monkeypatch.setattr(sweep, "_map", lambda *a: pytest.fail("ran before validation"))
    grid = Grid({"strategies": {"orb": {"params": {"min_rvol": [1.5], "rvol_min": [2.0]}}}})
    with pytest.raises(ValueError, match="rvol_min"):
        run_sweep(settings, grid, TRAIN, TEST, 1, "nowhere", SYMBOLS)
    with pytest.raises(ValueError, match="position_management.nope"):
        run_sweep(settings, Grid({"position_management": {"nope": [1]}}), TRAIN, TEST, 1, "nowhere", SYMBOLS)


@pytest.mark.parametrize("workers", [1, 2])
def test_train_only_ranking_and_no_db_rows(settings, cache_root, tmp_path, workers):
    engine = make_engine(tmp_path / "t.db")
    init_db(engine)
    result = _sweep(settings, cache_root, rvol_grid(top_k=1), workers)
    assert len(result.combos) == 3 and all(c.train["trades"] > 0 for c in result.combos)
    by_rvol = {c.overrides["strategies"]["orb"]["params"]["min_rvol"]: c for c in result.combos}
    # 3.0 is best on test but poor on train, so it must not be picked
    assert by_rvol[3.0].train["expectancy_r"] < by_rvol[2.0].train["expectancy_r"]
    assert [c.index for c in result.top] == [by_rvol[2.0].index]
    assert by_rvol[3.0].test is None and "by_strategy" in result.top[0].test
    with engine.connect() as conn:
        for table in (backtest_runs, signals, decisions, backtest_trades):
            assert conn.execute(select(func.count()).select_from(table)).scalar() == 0


def test_min_train_trades_excludes_combos(settings, cache_root):
    result = _sweep(settings, cache_root, rvol_grid(min_train_trades=999))
    assert result.top == [] and all(c.score is None for c in result.combos)
    assert "No configuration passes" in sweep.verdict(result)


def m(exp, trades=60, dd=1.0):
    return {"expectancy_r": exp, "trades": trades, "max_drawdown_r": dd}


def test_score_penalises_drawdown():
    assert sweep.score(m(0.5, dd=10.0), Grid({}, min_train_trades=40, drawdown_penalty=0.02)) == 0.3
    assert sweep.score(m(0.5, trades=39), Grid({})) is None


def test_overfit_flag():
    assert sweep.is_overfit(m(0.2), m(-0.01))
    assert sweep.is_overfit(m(0.9), m(0.5))
    assert not sweep.is_overfit(m(0.5), m(0.3))
    assert not sweep.is_overfit(m(-0.1), m(-0.2))


def test_gate(settings):
    limit = settings.capital.daily_loss_limit_r * 5
    assert sweep.passes_gate(settings, m(0.1), m(0.05, trades=40, dd=limit))
    assert not sweep.passes_gate(settings, m(0.1), m(0.0, trades=40))
    assert not sweep.passes_gate(settings, m(0.1), m(0.05, trades=39))
    assert not sweep.passes_gate(settings, m(0.1), m(0.05, trades=40, dd=limit + 0.01))


def _metrics(exp, trades):
    return {"trades": trades, "win_rate": 0.5, "expectancy_r": exp, "profit_factor": 1.2, "max_drawdown_r": 2.0,
            "by_strategy": {"orb": {"trades": trades, "win_rate": 0.5, "expectancy_r": exp}}}


def _result(pass_second: bool) -> SweepResult:
    a = ComboResult(0, {"position_management": {"stop_atr_min": 0.8}}, _metrics(0.3, 60), 0.26,
                    _metrics(-0.1, 30), True, False)
    b = ComboResult(1, {"strategies": {"orb": {"window_end": "10:30"}}}, _metrics(0.2, 60), 0.16,
                    _metrics(0.15, 50), False, pass_second)
    return SweepResult(Grid({}), TRAIN, TEST, 2, [a, b], [a, b])


def test_reports_and_recommended_yaml(settings, tmp_path):
    now = datetime(2026, 9, 14, 10, 0, tzinfo=IST)
    paths = sweep.write_reports(_result(True), settings, tmp_path, now)
    assert paths["md"].name == "sweep-20260914-100000.md"
    assert yaml.safe_load(paths["recommended"].read_text()) == {"strategies": {"orb": {"window_end": "10:30"}}}
    md = paths["md"].read_text()
    assert "1 configurations pass the out-of-sample gate" in md and "| orb | 50 |" in md
    assert '"verdict"' in paths["json"].read_text()
    paths = sweep.write_reports(_result(False), settings, tmp_path / "none", now)
    assert "recommended" not in paths and not list((tmp_path / "none").glob("*recommended*"))
    assert "No configuration passes — do not trust live alerts yet" in paths["md"].read_text()


@pytest.fixture
def cli_config(raw_config, tmp_path):
    raw_config["paths"]["data_dir"] = str(tmp_path / "data")
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(raw_config))
    return path


def _grid_file(tmp_path, overrides) -> str:
    path = tmp_path / "grid.yaml"
    path.write_text(yaml.safe_dump({"overrides": overrides, "min_train_trades": 1}))
    return str(path)


def _cli(config, grid, *extra):
    return cli.main(["--config", str(config), "sweep", "--grid", grid, "--train-from", TRAIN[0].isoformat(),
                     "--train-to", TRAIN[1].isoformat(), "--test-from", TEST[0].isoformat(),
                     "--test-to", TEST[1].isoformat(), "--workers", "1", *extra])


def test_cli_exit_codes(cli_config, cache_root, tmp_path, monkeypatch, capsys):
    assert _cli(cli_config, _grid_file(tmp_path, {"strategies": {"orb": {"bogus": [1]}}})) == 1
    assert "strategies.orb.bogus" in capsys.readouterr().err

    grid = _grid_file(tmp_path, {"strategies": {"orb": {"params": {"min_rvol": [1.5, 2.0]}}}})
    assert _cli(cli_config, grid) == 1  # empty candle cache
    assert "backfill" in capsys.readouterr().err

    real = sweep.run_sweep
    monkeypatch.setattr(sweep, "run_sweep", lambda s, g, train, test, workers, cache_root_, universe_, progress_cb,
                        **kw: real(s, g, train, test, workers, cache_root, SYMBOLS, progress_cb,
                                   classify=fake_classify, detect_all=param_detector, **kw))
    assert _cli(cli_config, grid, "--max-combinations", "1") == 0
    out = capsys.readouterr().out
    assert "combos 1/2" in out and "No configuration passes" in out
    reports = tmp_path / "data" / "reports"
    assert len(list(reports.glob("sweep-*.md"))) == 1 and len(list(reports.glob("sweep-*.partial.jsonl"))) == 1
    assert "peak worker RSS" in out


def test_missing_data_error_propagates(settings, tmp_path):
    with pytest.raises(MissingDataError):
        run_sweep(settings, rvol_grid(), TRAIN, TEST, 1, tmp_path, SYMBOLS)


def test_shortlist_cached_per_screener_settings(settings, cache_root, monkeypatch):
    calls = []
    monkeypatch.setattr(sweep, "_uncached_shortlist", lambda s, *a: calls.append(s.screener.shortlist_size) or ["AAA"])
    monkeypatch.setattr(sweep, "_WORKER", {})
    grid = Grid({"screener": {"shortlist_size": [5, 5, 6]}}, min_train_trades=999)
    _sweep(settings, cache_root, grid)
    assert replay.backtest_shortlist is sweep._ORIGINAL_SHORTLIST
    assert sorted(calls) == [5, 5, 6, 6]  # two train days per distinct screener config


def test_default_split_and_2025_holidays(settings):
    from tradalgo.clock import load_holidays
    assert sweep.DEFAULT_TRAIN == (date(2025, 10, 15), date(2026, 4, 30))
    assert sweep.DEFAULT_TEST == (date(2026, 5, 1), date(2026, 9, 11))
    assert {date(2025, 10, 21), date(2025, 10, 22), date(2025, 12, 25)} <= set(load_holidays(settings.paths.static_dir, 2025))


def test_overlapping_split_rejected(settings, cli_config, tmp_path, capsys):
    with pytest.raises(ValueError, match="overlap"):
        sweep.check_split((date(2026, 1, 1), date(2026, 5, 1)), (date(2026, 5, 1), date(2026, 6, 1)))
    with pytest.raises(ValueError, match="overlap"):
        run_sweep(settings, rvol_grid(), (TRAIN[0], TEST[1]), TEST, 1, "nowhere", SYMBOLS)
    grid = _grid_file(tmp_path, {"strategies": {"orb": {"params": {"min_rvol": [1.5]}}}})
    assert cli.main(["--config", str(cli_config), "sweep", "--grid", grid, "--train-from", "2026-01-01",
                     "--train-to", "2026-05-10", "--test-from", "2026-05-01", "--test-to", "2026-06-01"]) == 1
    assert "overlap" in capsys.readouterr().err


def test_default_workers_capped_at_four(monkeypatch):
    monkeypatch.setattr(sweep.os, "cpu_count", lambda: 16)
    assert sweep.default_workers() == 4
    monkeypatch.setattr(sweep.os, "cpu_count", lambda: 2)
    assert sweep.default_workers() == 1


def _ranking(result):
    return [(c.index, c.score, c.test, c.overfit, c.passes_gate) for c in result.top]


class Interrupt(Exception):
    pass


@pytest.mark.parametrize("workers", [1, 2])
def test_checkpoint_resume_matches_uninterrupted(settings, cache_root, tmp_path, workers):
    grid = rvol_grid(top_k=2)
    full = run_sweep(settings, grid, TRAIN, TEST, workers, cache_root, SYMBOLS, classify=fake_classify,
                     detect_all=param_detector, checkpoint=tmp_path / "full.partial.jsonl")
    assert full.peak_rss_mb > 0

    part = tmp_path / "cut.partial.jsonl"

    def stop_after_two(done, total, phase, rss):
        if done == 2:
            raise Interrupt

    with pytest.raises(Interrupt):
        run_sweep(settings, grid, TRAIN, TEST, 1, cache_root, SYMBOLS, stop_after_two, classify=fake_classify,
                  detect_all=param_detector, checkpoint=part)
    lines = [json.loads(line) for line in part.read_text().splitlines()]
    assert lines[0]["type"] == "header" and [e["phase"] for e in lines[1:]] == ["train", "train"]

    seen = []
    resumed = run_sweep(settings, grid, TRAIN, TEST, workers, cache_root, SYMBOLS,
                        lambda done, total, phase, rss: seen.append(done), classify=fake_classify,
                        detect_all=param_detector, checkpoint=part, resume=True)
    assert seen[0] == 3 and seen[-1] == 5
    assert _ranking(resumed) == _ranking(full)
    phases = [json.loads(line)["phase"] for line in part.read_text().splitlines()[1:]]
    assert phases == ["train"] * 3 + ["test"] * 2


def test_resume_rejects_different_grid_or_split(settings, cache_root, tmp_path):
    part = tmp_path / "x.partial.jsonl"
    _sweep_kw = dict(classify=fake_classify, detect_all=param_detector)
    run_sweep(settings, rvol_grid(top_k=1), TRAIN, TEST, 1, cache_root, SYMBOLS, checkpoint=part, **_sweep_kw)
    with pytest.raises(ValueError, match="does not match"):
        run_sweep(settings, rvol_grid(top_k=2), TRAIN, TEST, 1, cache_root, SYMBOLS, checkpoint=part, resume=True,
                  **_sweep_kw)
    with pytest.raises(ValueError, match="does not match"):
        run_sweep(settings, rvol_grid(top_k=1), (TRAIN[0], TRAIN[0]), TEST, 1, cache_root, SYMBOLS,
                  checkpoint=part, resume=True, **_sweep_kw)


def test_report_shows_peak_rss(settings, tmp_path):
    result = _result(True)
    result.peak_rss_mb = 321.5
    paths = sweep.write_reports(result, settings, tmp_path, datetime(2026, 9, 14, 10, 0, tzinfo=IST))
    assert "Peak worker RSS: 321.5 MB" in paths["md"].read_text()
    assert json.loads(paths["json"].read_text())["peak_rss_mb"] == 321.5
