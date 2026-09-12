"""Plan requirement: changing candles after time T must never change any signal or decision before T."""
from datetime import timedelta

import numpy as np
import pandas as pd
from sqlalchemy import select

from tradalgo.backtest.replay import run_backtest
from tradalgo.storage import repo
from tradalgo.storage.db import init_db, make_engine
from tradalgo.storage.schema import decisions, signals
from tradalgo.strategies.base import Signal
from tests.backtest_fixtures import REPLAY_DAYS, at, build_replay_cache, fake_classify, replay_params, universe

DAY = REPLAY_DAYS[0]
T = at(11, 0, DAY)


def wild_after(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    rng = np.random.default_rng(7)
    mask = df.index >= pd.Timestamp(T)
    n = int(mask.sum())
    o, c = rng.uniform(50, 400, n), rng.uniform(50, 400, n)
    df.loc[mask, "open"], df.loc[mask, "close"] = o, c
    df.loc[mask, "high"] = np.maximum(o, c) + rng.uniform(0, 30, n)
    df.loc[mask, "low"] = np.minimum(o, c) - rng.uniform(0, 30, n)
    df.loc[mask, "volume"] = rng.uniform(1, 1e7, n)
    return df


def every_bar_detector(ctx, settings, calendar):
    last = ctx.candles_5m.index[-1]
    assert last + timedelta(minutes=5) <= ctx.now
    assert ctx.candles_15m.index[-1] + timedelta(minutes=15) <= ctx.now
    assert ctx.index_15m.index[-1] + timedelta(minutes=15) <= ctx.now
    assert ctx.daily.index[-1].date() < ctx.now.date()
    close = float(ctx.candles_5m["close"].iloc[-1])
    features = {"frame_high": float(ctx.candles_5m["high"].max()), "c15_close": float(ctx.candles_15m["close"].iloc[-1]),
                "index_close": float(ctx.index_15m["close"].iloc[-1])}
    return [Signal(ctx.symbol, "vwap", "long", last.to_pydatetime(), close, close - 1.0, ctx.regime,
                   ctx.market_regime, False, "fake", features)]


def replay(tmp_path, name, alter=None):
    engine = make_engine(tmp_path / f"{name}.db")
    init_db(engine)
    cache = build_replay_cache(tmp_path / name, alter)
    params = replay_params(DAY, DAY)
    run_id = repo.enqueue_backtest_run(engine, params, at(8, 0, DAY))
    run_backtest(engine=engine, settings=SETTINGS[0], params=params, run_id=run_id, cache=cache,
                 universe=universe(["AAA", "BBB", "CCC"]), classify=fake_classify, detect_all=every_bar_detector)
    with engine.connect() as conn:
        rows = conn.execute(
            select(signals.c.ts, signals.c.symbol, signals.c.strategy, signals.c.entry, signals.c.stop_loss,
                   signals.c.features_json, decisions.c.accepted, decisions.c.rejection_reason, decisions.c.qty,
                   decisions.c.expected_value_r, decisions.c.room_to_target_r)
            .join(decisions, decisions.c.signal_id == signals.c.id).order_by(signals.c.id)
        ).all()
    return [tuple(r) for r in rows]


SETTINGS = []


def test_future_candles_never_change_past_decisions(settings, tmp_path):
    SETTINGS[:] = [settings]
    base = replay(tmp_path, "base")
    altered = replay(tmp_path, "altered", wild_after)
    before = lambda rows: [r for r in rows if r[0] < T.isoformat()]
    assert len(before(base)) > 10
    assert before(base) == before(altered)
    assert base != altered  # the alteration really reached the engine after T
