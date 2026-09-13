"""Logic extracted from the Streamlit pages (tradalgo/dashboard/pages/*.py), which will be
deleted at B4. Kept here, tested here, and imported by the API routes.
"""
import json
from datetime import datetime, timedelta

import pandas as pd
from sqlalchemy import Engine, text

from tradalgo.api import now as now_mod
from tradalgo.clock import IST
from tradalgo.dashboard import controls, queries
from tradalgo.data.candle_cache import CandleCache


# ---- 1_today.py: Now-strip list assembly ----------------------------------------------------

def now_strip_payload(engine: Engine, data_dir, trade_date: str, when: datetime | None = None) -> dict:
    when = when or datetime.now(IST)
    kill_on = controls.kill_switch_active(data_dir)
    alerts = queries.alerts_log(engine, trade_date=trade_date)

    failed = alerts[alerts["status"] == "failed"].to_dict("records") if not alerts.empty else []
    awaiting = []
    if not alerts.empty:
        pending = alerts[(alerts["alert_type"] == "entry") & alerts["user_action"].isna()
                         & (alerts["status"] != "failed")]
        for row in pending.to_dict("records"):
            awaiting.append({"symbol": row["symbol"], "text": row.get("text") or "",
                             "valid_until": row.get("valid_until") or "unknown",
                             "direction": row.get("direction"), "entry": row.get("entry"),
                             "stop": row.get("stop_loss")})

    positions = queries.trade_positions(engine)
    open_trades = positions[positions["exit_ts"].isna()].to_dict("records") if not positions.empty else []

    next_check = (when + timedelta(minutes=15)).strftime("%H:%M")
    state = now_mod.now_strip_state(
        kill_switch_on=kill_on, failed_alerts=failed, awaiting_alerts=awaiting,
        open_trades=open_trades, next_check=next_check,
    )
    return {"headline": state.headline, "quiet": state.quiet}


# ---- 2_positions.py: awaiting-reply flag + candle/level assembly ----------------------------

def awaiting_reply(alerts_df: pd.DataFrame, signal_id, now: datetime | None = None) -> bool:
    """A signal's entry alert is awaiting the user's reply: sent, no user action yet,
    and not past its valid_until.
    """
    if alerts_df.empty:
        return False
    now = now or datetime.now(IST)
    rows = alerts_df[(alerts_df["signal_id"] == signal_id) & (alerts_df["alert_type"] == "entry")
                      & (alerts_df["status"] == "sent") & alerts_df["user_action"].isna()]
    if rows.empty:
        return False
    for valid_until in rows["valid_until"]:
        if valid_until is None:
            return True
        try:
            if pd.Timestamp(valid_until) >= now:
                return True
        except (TypeError, ValueError):
            return True
    return False


def session_vwap(candles: pd.DataFrame) -> pd.Series:
    typical = (candles["high"] + candles["low"] + candles["close"]) / 3
    pv = typical * candles["volume"]
    cum_vol = candles["volume"].cumsum().replace(0, pd.NA)
    return (pv.cumsum() / cum_vol).astype(float)


def candles_to_json(candles: pd.DataFrame) -> list[dict]:
    """[{time (unix seconds), open, high, low, close, volume}], the lightweight-charts shape."""
    if candles.empty:
        return []
    out = []
    for ts, row in candles.iterrows():
        out.append({
            "time": int(pd.Timestamp(ts).timestamp()),
            "open": float(row["open"]), "high": float(row["high"]),
            "low": float(row["low"]), "close": float(row["close"]),
            "volume": float(row["volume"]),
        })
    return out


def vwap_to_json(candles: pd.DataFrame) -> list[dict]:
    if candles.empty:
        return []
    vwap = session_vwap(candles)
    return [{"time": int(pd.Timestamp(ts).timestamp()), "value": float(v)}
            for ts, v in vwap.items() if pd.notna(v)]


def day_candles(cache: CandleCache, symbol: str, day) -> pd.DataFrame:
    """That symbol's whole session for `day`. Empty frame (not an error) when nothing is cached."""
    candles = cache.load(symbol, "5m")
    if candles.empty:
        return candles
    return candles[candles.index.date == day]


# ---- 3_telegram.py: counts -------------------------------------------------------------------

def alert_counts(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"sent": 0, "failed": 0, "awaiting": 0}
    sent = int((df["status"] == "sent").sum())
    failed = int((df["status"] == "failed").sum())
    awaiting = int(df["user_action"].isna().sum()) if "user_action" in df.columns else 0
    return {"sent": sent, "failed": failed, "awaiting": awaiting}


# ---- 4_backtest.py: gate verdict --------------------------------------------------------------

def backtest_gate(metrics: dict) -> dict:
    trades_n = metrics.get("trades") or 0
    expectancy = metrics.get("expectancy_r")
    passed = trades_n >= 100 and expectancy is not None and expectancy > 0
    if passed:
        reason = f"{trades_n} trades, expectancy {expectancy:.2f}R after costs and slippage."
    elif trades_n < 100:
        reason = f"fewer than 100 trades ({trades_n})."
    else:
        reason = f"expectancy is not positive after costs ({expectancy}R)."
    return {"passed": passed, "reason": reason}


# ---- 7_health.py: FYERS refresh token expiry ---------------------------------------------------

def safe_refresh_token_expiry(store) -> str | None:
    from tradalgo.data.fyers_auth import refresh_token_expiry
    try:
        expiry = refresh_token_expiry(store)
        return expiry.isoformat() if expiry else None
    except Exception:
        return None


# ---- backtest trade replay: legs_json (per-leg events), when the column exists -----------------

_MARKER_KIND = {
    "partial_exit": "partial_exit", "stop_hit": "stop_hit", "runner_exit": "runner_exit",
    "hard_exit": "hard_exit", "trail_update": "trail_update", "target": "runner_exit",
    "entry": "entry",
}


def load_backtest_trade(engine: Engine, run_id: int, trade_id: int) -> dict | None:
    """Selects every column `backtest_trades` actually has (via `SELECT *`), so this works whether
    or not a `legs_json` column has been migrated in yet — no dependency on storage/schema.py's
    Table object having a column definition for it.
    """
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM backtest_trades WHERE id = :id AND backtest_run_id = :run_id"),
            {"id": trade_id, "run_id": run_id},
        ).mappings().first()
    return dict(row) if row is not None else None


def _epoch(ts) -> int:
    return int(pd.Timestamp(ts).timestamp())


def trade_replay_markers(trade: dict, entry_stop: float | None) -> dict:
    """{"markers": [...], "stop_path": [...]}.

    When `legs_json` (a JSON list of {kind, ts, price, qty, r, new_stop?}) is present and parses,
    every leg becomes a marker in order and each trail_update's new_stop steps the stop_path.
    Otherwise (column missing, NULL, or unparseable) falls back to entry + the row's own final
    exit fields, with a flat stop_path at the entry stop.
    """
    entry_marker = {"time": _epoch(trade["entry_ts"]), "kind": "entry",
                    "price": trade["entry_price"], "qty": trade["qty"], "r": 0.0}
    stop_path = [{"time": _epoch(trade["entry_ts"]), "value": entry_stop}]

    legs_raw = trade.get("legs_json")
    legs = None
    if legs_raw:
        try:
            legs = json.loads(legs_raw)
        except (TypeError, ValueError):
            legs = None

    if legs:
        markers = [entry_marker]
        for leg in legs:
            kind = _MARKER_KIND.get(leg.get("kind"), leg.get("kind"))
            markers.append({"time": _epoch(leg["ts"]), "kind": kind, "price": leg.get("price"),
                            "qty": leg.get("qty"), "r": leg.get("r")})
            if leg.get("kind") == "trail_update" and leg.get("new_stop") is not None:
                stop_path.append({"time": _epoch(leg["ts"]), "value": leg["new_stop"]})
        return {"markers": markers, "stop_path": stop_path}

    exit_marker = {
        "time": _epoch(trade["exit_ts"]),
        "kind": _MARKER_KIND.get(trade["exit_reason"], trade["exit_reason"]),
        "price": trade["exit_price"], "qty": trade["qty"], "r": trade["net_r"],
    }
    return {"markers": [entry_marker, exit_marker], "stop_path": stop_path}
