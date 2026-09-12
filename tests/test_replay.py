from datetime import date, time

import pytest
from sqlalchemy import func, select

from tradalgo.backtest.replay import BacktestCancelled, MissingDataError, apply_params, run_backtest
from tradalgo.storage import repo
from tradalgo.storage.db import init_db, make_engine
from tradalgo.storage.schema import backtest_trades, shortlist, signals
from tradalgo.strategies.base import Signal
from tests.backtest_fixtures import (
    REPLAY_DAYS, REPLAY_SYMBOLS, at, build_replay_cache, fake_classify, replay_params, universe,
)

CONTRACT_KEYS = {"trades", "win_rate", "expectancy_r", "expectancy_r_no_slippage", "profit_factor",
                 "max_drawdown_r", "net_r", "net_rupees", "by_strategy", "by_regime"}


@pytest.fixture
def engine(tmp_path):
    eng = make_engine(tmp_path / "t.db")
    init_db(eng)
    return eng


def once_per_day_detector():
    fired = set()

    def detect(ctx, settings, calendar):
        last = ctx.candles_5m.index[-1]
        if last.time() != time(9, 40) or last.date() in fired:
            return []
        fired.add(last.date())
        close = float(ctx.candles_5m["close"].iloc[-1])
        return [Signal(ctx.symbol, "orb", "long", last.to_pydatetime(), close, close - 1.0, ctx.regime,
                       ctx.market_regime, False, "fake", {"close": close})]
    return detect


def _run(settings, engine, cache, params, **kw):
    run_id = repo.enqueue_backtest_run(engine, params, at(8, 0))
    progress = []
    metrics = run_backtest(settings, engine, params, run_id, cache, universe(["AAA", "BBB", "CCC"]),
                           progress.append, classify=fake_classify, detect_all=once_per_day_detector(), **kw)
    return run_id, progress, metrics


def test_three_day_smoke(settings, engine, tmp_path):
    cache = build_replay_cache(tmp_path / "candles")
    run_id, progress, metrics = _run(settings, engine, cache, replay_params(REPLAY_DAYS[0], REPLAY_DAYS[-1]))
    assert set(metrics) == CONTRACT_KEYS
    assert metrics["trades"] == 3 and metrics["win_rate"] == 1.0
    assert set(metrics["by_strategy"]) == {"orb"} and set(metrics["by_regime"]) == {"trend_up"}
    assert progress == [33.3, 66.7, 100.0]
    with engine.connect() as conn:
        rows = conn.execute(select(backtest_trades).where(backtest_trades.c.backtest_run_id == run_id)).all()
        n_signals = conn.execute(select(func.count()).select_from(signals).where(
            signals.c.mode == "backtest", signals.c.backtest_run_id == run_id)).scalar()
        assert conn.execute(select(func.count()).select_from(shortlist)).scalar() == 0
    assert [r.trade_date for r in rows] == [d.isoformat() for d in REPLAY_DAYS]
    assert {r.exit_reason for r in rows} == {"runner_exit"}
    assert n_signals == 3


def test_cancel_between_days(settings, engine, tmp_path):
    cache = build_replay_cache(tmp_path / "candles")
    params = replay_params(REPLAY_DAYS[0], REPLAY_DAYS[-1])
    run_id = repo.enqueue_backtest_run(engine, params, at(8, 0))
    progress = []
    with pytest.raises(BacktestCancelled):
        run_backtest(settings, engine, params, run_id, cache, universe(["AAA", "BBB", "CCC"]), progress.append,
                     lambda: len(progress) >= 1, classify=fake_classify, detect_all=once_per_day_detector())
    assert progress == [33.3]
    with engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(backtest_trades)).scalar() == 1


def test_missing_cache_data_fails_with_backfill_hint(settings, engine, tmp_path):
    cache = build_replay_cache(tmp_path / "candles")
    with pytest.raises(MissingDataError, match="tradalgo backfill"):
        _run(settings, engine, cache, replay_params(REPLAY_DAYS[0], date(2026, 9, 18)))


def test_params_override_without_mutating_settings(settings):
    params = {**replay_params(REPLAY_DAYS[0], REPLAY_DAYS[0]), "strategies": ["orb"], "max_risk_pct": 0.01,
              "shortlist_size": 5, "slippage_pct": 0.2, "initial_capital": 50000.0}
    s = apply_params(settings, params)
    assert s.capital.max_risk_pct == 0.01 and s.capital.initial_capital == 50000.0
    assert s.screener.shortlist_size == 5 and s.backtest.slippage_pct == 0.2
    assert [n for n, c in s.strategies.items() if c.enabled] == ["orb"]
    assert settings.capital.max_risk_pct == 0.03 and all(c.enabled for c in settings.strategies.values())
    assert set(REPLAY_SYMBOLS) >= {"AAA"}
