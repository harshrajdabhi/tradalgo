"""Logic extracted from the Streamlit pages (tradalgo/dashboard/pages/*.py), which will be
deleted at B4. Kept here, tested here, and imported by the API routes.
"""
from datetime import datetime, timedelta

import pandas as pd
from sqlalchemy import Engine

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


# ---- 8_settings.py: full-config replace (moved server-side) -----------------------------------

def merged_settings(current: dict, new_partial: dict) -> dict:
    """Shallow-merge top-level sections; the API accepts a full config dict from the client, so
    this mainly guards against a client sending a partial document by mistake.
    """
    out = dict(current)
    out.update(new_partial)
    return out
