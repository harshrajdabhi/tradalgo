from datetime import datetime

import json

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import Engine, select

from tradalgo.api import services
from fastapi import Request

from tradalgo.api.deps import get_engine, settings_for_request
from tradalgo.api.models import BacktestParams, GateResult
from tradalgo.api.util import df_records
from tradalgo.backtest import diagnostics
from tradalgo.clock import IST
from tradalgo.config import Settings
from tradalgo.dashboard import controls, queries
from tradalgo.storage.schema import backtest_trades

router = APIRouter(prefix="/api/backtests", tags=["backtests"])


def _settings(request: Request) -> Settings:
    return settings_for_request(request)


def _engine(settings: Settings = Depends(_settings)) -> Engine:
    return get_engine(settings)


@router.get("")
def list_backtests(engine: Engine = Depends(_engine)):
    return df_records(queries.backtest_runs_list(engine))


@router.post("", status_code=201)
def create_backtest(params: BacktestParams, engine: Engine = Depends(_engine)):
    try:
        run_id = controls.queue_backtest(engine, params.to_dict(), datetime.now(IST))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"id": run_id}


@router.post("/{run_id}/cancel")
def cancel_backtest(run_id: int, engine: Engine = Depends(_engine)):
    controls.request_cancel_backtest(engine, run_id)
    return {"ok": True}


def _run_row(engine: Engine, run_id: int) -> dict:
    df = queries.backtest_runs_list(engine)
    matches = df[df["id"] == run_id] if not df.empty else df
    if matches.empty:
        raise HTTPException(status_code=404, detail=f"backtest run {run_id} not found")
    return df_records(matches)[0]


@router.get("/{run_id}")
def get_backtest(run_id: int, engine: Engine = Depends(_engine)):
    run = _run_row(engine, run_id)
    metrics = queries.backtest_run_metrics(engine, run_id)
    gate = services.backtest_gate(metrics) if metrics else GateResult(passed=False, reason="no metrics yet").model_dump()
    trades = queries.backtest_run_trades(engine, run_id)
    diag = None
    if not trades.empty:
        run_data = diagnostics.load_run(engine, run_id)
        diag = diagnostics.diagnose(run_data)
    return {
        "run": run,
        "params": json.loads(run["params_json"]) if run.get("params_json") else None,
        "metrics": metrics,
        "gate": gate,
        "diagnostics": diag,
    }


@router.get("/{run_id}/live")
def get_backtest_live(run_id: int, engine: Engine = Depends(_engine)):
    run = _run_row(engine, run_id)
    trades = queries.backtest_run_trades(engine, run_id)

    net_r = trades["net_r"].tolist() if not trades.empty else []
    n = len(net_r)
    win_rate = round(sum(r > 0 for r in net_r) / n, 4) if n else None
    expectancy_r = round(sum(net_r) / n, 4) if n else None
    net_r_total = round(sum(net_r), 4) if n else None

    cum = 0.0
    peak = 0.0
    drawdown = 0.0
    equity_curve = []
    for i, row in enumerate(trades.itertuples(), start=1):
        cum += row.net_r
        peak = max(peak, cum)
        drawdown = max(drawdown, peak - cum)
        equity_curve.append({"trade_index": i, "exit_ts": row.exit_ts, "cum_net_r": round(cum, 4)})

    r_histogram = []
    if n:
        import numpy as np
        counts, edges = np.histogram(net_r, bins=20)
        r_histogram = [{"bin_start": round(float(edges[i]), 4), "bin_end": round(float(edges[i + 1]), 4),
                        "count": int(counts[i])} for i in range(len(counts))]

    by_strategy = []
    if not trades.empty:
        for strat, g in trades.groupby("strategy"):
            g_net = g["net_r"].tolist()
            by_strategy.append({
                "strategy": strat, "trades": len(g_net),
                "win_rate": round(sum(r > 0 for r in g_net) / len(g_net), 4),
                "expectancy_r": round(sum(g_net) / len(g_net), 4),
            })

    latest_trades = df_records(trades.tail(20)) if not trades.empty else []

    return {
        "status": run["status"],
        "progress_pct": run.get("progress_pct"),
        "trades_so_far": n,
        "win_rate": win_rate,
        "expectancy_r": expectancy_r,
        "net_r": net_r_total,
        "max_drawdown_r": round(drawdown, 4) if n else None,
        "equity_curve": equity_curve,
        "r_histogram": r_histogram,
        "by_strategy": by_strategy,
        "latest_trades": latest_trades,
    }


@router.get("/{run_id}/trades")
def get_backtest_trades(run_id: int, strategy: str | None = None, symbol: str | None = None,
                        outcome: str | None = None, engine: Engine = Depends(_engine)):
    df = queries.backtest_run_trades(engine, run_id)
    if not df.empty:
        if strategy:
            df = df[df["strategy"] == strategy]
        if symbol:
            df = df[df["symbol"] == symbol]
        if outcome == "win":
            df = df[df["net_r"] > 0]
        elif outcome == "loss":
            df = df[df["net_r"] <= 0]
    return df_records(df)


_MARKER_KIND = {
    "partial_exit": "partial_exit", "stop_hit": "stop_hit", "runner_exit": "runner_exit",
    "hard_exit": "hard_exit", "trail_update": "trail_update", "target": "runner_exit",
}


@router.get("/{run_id}/trades/{trade_id}/replay")
def get_trade_replay(run_id: int, trade_id: int, engine: Engine = Depends(_engine),
                     settings: Settings = Depends(_settings)):
    with engine.connect() as conn:
        row = conn.execute(
            select(backtest_trades).where(backtest_trades.c.id == trade_id,
                                          backtest_trades.c.backtest_run_id == run_id)
        ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"trade {trade_id} not found in run {run_id}")
    trade = dict(row)

    from tradalgo.data.candle_cache import CandleCache
    cache = CandleCache(settings.paths.data_dir / "candles", provider=None)
    day = pd.Timestamp(trade["entry_ts"]).date()
    candles = services.day_candles(cache, trade["symbol"], day)

    sig_df = queries.signals_with_decisions(engine, day.isoformat())
    levels = {"entry": trade["entry_price"], "stop": None, "target_partial": None, "target_runner": None}
    if not sig_df.empty and trade.get("signal_id") is not None:
        sig_rows = sig_df[sig_df["signal_id"] == trade["signal_id"]]
        if not sig_rows.empty:
            sig = sig_rows.iloc[0]
            levels = {"entry": trade["entry_price"], "stop": sig.get("stop_loss"),
                     "target_partial": sig.get("target_2r"), "target_runner": sig.get("target_3r")}

    markers = [{
        "time": int(pd.Timestamp(trade["entry_ts"]).timestamp()), "kind": "entry",
        "price": trade["entry_price"], "qty": trade["qty"], "r": 0.0,
    }, {
        "time": int(pd.Timestamp(trade["exit_ts"]).timestamp()),
        "kind": _MARKER_KIND.get(trade["exit_reason"], trade["exit_reason"]),
        "price": trade["exit_price"], "qty": trade["qty"], "r": trade["net_r"],
    }]

    return {
        "trade": trade,
        "candles": services.candles_to_json(candles),
        "session_vwap": services.vwap_to_json(candles),
        "levels": levels,
        "markers": markers,
    }
