"""Read-only queries: plain functions (engine, ...) -> pandas.DataFrame. No Streamlit import here."""
import json

import pandas as pd
from sqlalchemy import Engine, text


def _read(engine: Engine, sql: str, params: dict | None = None) -> pd.DataFrame:
    with engine.connect() as conn:
        return pd.read_sql(text(sql), conn, params=params or {})


def shortlist_for_date(engine: Engine, trade_date: str) -> pd.DataFrame:
    return _read(engine, """
        SELECT rank, symbol, composite_score, factor_scores_json, reasons, gap_pct, demoted
        FROM shortlist WHERE trade_date = :d ORDER BY rank
    """, {"d": trade_date})


def signals_with_decisions(engine: Engine, trade_date: str) -> pd.DataFrame:
    return _read(engine, """
        SELECT s.id AS signal_id, s.ts, s.symbol, s.strategy, s.direction, s.regime, s.market_regime,
               s.entry, s.stop_loss, s.target_2r, s.target_3r, s.features_json,
               d.accepted, d.rejection_reason, d.qty, d.risk_rupees, d.expected_value_r, d.room_to_target_r
        FROM signals s
        LEFT JOIN decisions d ON d.signal_id = s.id
        WHERE s.mode = 'live' AND date(s.ts) = :d
        ORDER BY s.ts
    """, {"d": trade_date})


def positions(engine: Engine) -> pd.DataFrame:
    return _read(engine, """
        SELECT p.id AS trade_id, p.signal_id, p.taken_by_user, p.entry_ts, p.entry_price, p.qty,
               p.partial_exit_ts, p.partial_exit_price, p.exit_ts, p.exit_price, p.exit_reason,
               p.mfe_r, p.mae_r, p.gross_r, p.net_r,
               s.symbol, s.strategy, s.direction, s.stop_loss, s.target_2r, s.target_3r, s.ts AS signal_ts,
               ua.action AS user_action
        FROM paper_trades p
        JOIN signals s ON s.id = p.signal_id
        LEFT JOIN user_actions ua ON ua.alert_id = (
            SELECT a.id FROM alerts a WHERE a.signal_id = s.id ORDER BY a.id LIMIT 1
        )
        ORDER BY p.entry_ts DESC
    """)


def alerts_log(engine: Engine, status: str | None = None, trade_date: str | None = None) -> pd.DataFrame:
    clauses = []
    params: dict = {}
    if status:
        clauses.append("a.status = :status")
        params["status"] = status
    if trade_date:
        clauses.append("date(a.created_at) = :d")
        params["d"] = trade_date
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return _read(engine, f"""
        SELECT a.id AS alert_id, a.dedup_key, a.alert_type, a.symbol, a.signal_id, a.text, a.status,
               a.created_at, a.sent_at, a.latency_ms, a.attempts, a.last_error, a.valid_until,
               ua.action AS user_action
        FROM alerts a
        LEFT JOIN user_actions ua ON ua.alert_id = a.id
        {where}
        ORDER BY a.created_at DESC
    """, params)


def backtest_runs_list(engine: Engine) -> pd.DataFrame:
    return _read(engine, """
        SELECT id, created_at, started_at, finished_at, status, params_json, progress_pct, metrics_json, error
        FROM backtest_runs ORDER BY id DESC
    """)


def backtest_run_metrics(engine: Engine, run_id: int) -> dict:
    df = _read(engine, "SELECT metrics_json FROM backtest_runs WHERE id = :id", {"id": run_id})
    if df.empty or not df.iloc[0]["metrics_json"]:
        return {}
    return json.loads(df.iloc[0]["metrics_json"])


def backtest_run_trades(engine: Engine, run_id: int) -> pd.DataFrame:
    return _read(engine, """
        SELECT id, signal_id, trade_date, symbol, strategy, direction, entry_ts, entry_price,
               exit_ts, exit_price, exit_reason, qty, mfe_r, mae_r, gross_r, net_r
        FROM backtest_trades WHERE backtest_run_id = :id ORDER BY entry_ts
    """, {"id": run_id})


def journal(engine: Engine, date_from: str | None = None, date_to: str | None = None,
            strategy: str | None = None, symbol: str | None = None) -> pd.DataFrame:
    clauses = []
    params: dict = {}
    if date_from:
        clauses.append("date(s.ts) >= :from_")
        params["from_"] = date_from
    if date_to:
        clauses.append("date(s.ts) <= :to_")
        params["to_"] = date_to
    if strategy:
        clauses.append("s.strategy = :strategy")
        params["strategy"] = strategy
    if symbol:
        clauses.append("s.symbol = :symbol")
        params["symbol"] = symbol
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return _read(engine, f"""
        SELECT s.id AS signal_id, s.ts, s.symbol, s.strategy, s.direction, s.mode,
               d.accepted, d.rejection_reason,
               p.entry_price, p.exit_price, p.exit_reason, p.gross_r, p.net_r
        FROM signals s
        LEFT JOIN decisions d ON d.signal_id = s.id
        LEFT JOIN paper_trades p ON p.signal_id = s.id
        {where}
        ORDER BY s.ts DESC
    """, params)


def expectancy_by(engine: Engine, group_col: str) -> pd.DataFrame:
    col_map = {
        "strategy": "s.strategy",
        "regime": "s.regime",
        "symbol": "s.symbol",
        "hour": "CAST(strftime('%H', p.entry_ts) AS INTEGER)",
    }
    col = col_map[group_col]
    return _read(engine, f"""
        SELECT {col} AS grp,
               COUNT(*) AS trades,
               AVG(CASE WHEN p.net_r > 0 THEN 1.0 ELSE 0.0 END) AS win_rate,
               AVG(p.net_r) AS expectancy_r
        FROM paper_trades p
        JOIN signals s ON s.id = p.signal_id
        WHERE p.exit_ts IS NOT NULL
        GROUP BY grp
        ORDER BY grp
    """)


def mfe_mae_points(engine: Engine) -> pd.DataFrame:
    return _read(engine, """
        SELECT symbol, strategy, mfe_r, mae_r, net_r FROM paper_trades p
        JOIN signals s ON s.id = p.signal_id
        WHERE p.mfe_r IS NOT NULL AND p.mae_r IS NOT NULL
    """)


def live_vs_backtest_expectancy(engine: Engine) -> pd.DataFrame:
    live = _read(engine, """
        SELECT s.strategy, AVG(p.net_r) AS live_expectancy_r, COUNT(*) AS live_trades
        FROM paper_trades p JOIN signals s ON s.id = p.signal_id
        WHERE p.exit_ts IS NOT NULL
        GROUP BY s.strategy
    """)
    backtest = _read(engine, """
        SELECT strategy, AVG(net_r) AS backtest_expectancy_r, COUNT(*) AS backtest_trades
        FROM backtest_trades GROUP BY strategy
    """)
    if live.empty and backtest.empty:
        return pd.DataFrame(columns=["strategy", "live_expectancy_r", "live_trades",
                                      "backtest_expectancy_r", "backtest_trades"])
    return pd.merge(live, backtest, on="strategy", how="outer")


def latest_job_runs(engine: Engine) -> pd.DataFrame:
    return _read(engine, """
        SELECT job, run_date, started_at, finished_at, status, error
        FROM job_runs j
        WHERE id = (SELECT MAX(id) FROM job_runs j2 WHERE j2.job = j.job)
        ORDER BY job
    """)


def health_events(engine: Engine, limit: int = 200) -> pd.DataFrame:
    return _read(engine, """
        SELECT ts, component, level, message FROM health_events
        ORDER BY id DESC LIMIT :limit
    """, {"limit": limit})


def degraded_periods(engine: Engine, component: str = "data") -> pd.DataFrame:
    return _read(engine, """
        SELECT ts, component, level, message FROM health_events
        WHERE component = :c AND level IN ('warning', 'error')
        ORDER BY ts DESC
    """, {"c": component})
