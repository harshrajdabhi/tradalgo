from sqlalchemy import (
    CheckConstraint, Column, Float, ForeignKey, Integer, MetaData, String, Table, Text,
)

# Timestamps are stored as ISO-8601 strings with IST offset; SQLite DateTime drops tzinfo.
metadata = MetaData()

ALERT_STATUSES = ("queued", "sent", "failed", "edited", "expired")
BACKTEST_STATUSES = ("queued", "running", "done", "failed", "cancel_requested", "cancelled")


def _in(col: str, values: tuple[str, ...]) -> CheckConstraint:
    return CheckConstraint(f"{col} IN ({', '.join(repr(v) for v in values)})")


job_runs = Table(
    "job_runs", metadata,
    Column("id", Integer, primary_key=True),
    Column("job", String, nullable=False),
    Column("run_date", String, nullable=False),
    Column("started_at", String, nullable=False),
    Column("finished_at", String),
    Column("status", String, nullable=False),
    Column("error", Text),
    _in("status", ("running", "succeeded", "failed")),
)

shortlist = Table(
    "shortlist", metadata,
    Column("id", Integer, primary_key=True),
    Column("trade_date", String, nullable=False),
    Column("rank", Integer, nullable=False),
    Column("symbol", String, nullable=False),
    Column("composite_score", Float, nullable=False),
    Column("factor_scores_json", Text, nullable=False),
    Column("reasons", Text),
    Column("gap_pct", Float),
    Column("demoted", Integer, nullable=False, default=0),
)

signals = Table(
    "signals", metadata,
    Column("id", Integer, primary_key=True),
    Column("ts", String, nullable=False),
    Column("symbol", String, nullable=False),
    Column("strategy", String, nullable=False),
    Column("direction", String, nullable=False),
    Column("regime", String, nullable=False),
    Column("market_regime", String),
    Column("entry", Float, nullable=False),
    Column("stop_loss", Float, nullable=False),
    Column("target_2r", Float, nullable=False),
    Column("target_3r", Float, nullable=False),
    Column("features_json", Text, nullable=False),
    Column("mode", String, nullable=False),
    Column("backtest_run_id", Integer, ForeignKey("backtest_runs.id")),
    _in("direction", ("long", "short")),
    _in("mode", ("live", "backtest")),
)

decisions = Table(
    "decisions", metadata,
    Column("id", Integer, primary_key=True),
    Column("signal_id", Integer, ForeignKey("signals.id"), nullable=False),
    Column("accepted", Integer, nullable=False),
    Column("rejection_reason", Text),
    Column("qty", Integer),
    Column("leverage_used", Float),
    Column("risk_rupees", Float),
    Column("est_cost", Float),
    Column("expected_value_r", Float),
    Column("room_to_target_r", Float),
)

alerts = Table(
    "alerts", metadata,
    Column("id", Integer, primary_key=True),
    Column("dedup_key", String, nullable=False, unique=True),
    Column("alert_type", String, nullable=False),
    Column("symbol", String),
    Column("signal_id", Integer, ForeignKey("signals.id")),
    Column("text", Text, nullable=False),
    Column("status", String, nullable=False),
    Column("created_at", String, nullable=False),
    Column("sent_at", String),
    Column("latency_ms", Integer),
    Column("telegram_message_id", Integer),
    Column("attempts", Integer, nullable=False, default=0),
    Column("last_error", Text),
    Column("valid_until", String),
    _in("status", ALERT_STATUSES),
)

user_actions = Table(
    "user_actions", metadata,
    Column("id", Integer, primary_key=True),
    Column("alert_id", Integer, ForeignKey("alerts.id"), nullable=False),
    Column("action", String, nullable=False),
    Column("price", Float),
    Column("ts", String, nullable=False),
    _in("action", ("taken", "skipped", "kill", "status")),
)

paper_trades = Table(
    "paper_trades", metadata,
    Column("id", Integer, primary_key=True),
    Column("signal_id", Integer, ForeignKey("signals.id"), nullable=False),
    Column("taken_by_user", Integer, nullable=False, default=0),
    Column("entry_ts", String, nullable=False),
    Column("entry_price", Float, nullable=False),
    Column("qty", Integer, nullable=False),
    Column("partial_exit_ts", String),
    Column("partial_exit_price", Float),
    Column("exit_ts", String),
    Column("exit_price", Float),
    Column("exit_reason", String),
    Column("mfe_r", Float),
    Column("mae_r", Float),
    Column("slippage_rupees", Float),
    Column("gross_r", Float),
    Column("net_r", Float),
)

backtest_runs = Table(
    "backtest_runs", metadata,
    Column("id", Integer, primary_key=True),
    Column("created_at", String, nullable=False),
    Column("started_at", String),
    Column("finished_at", String),
    Column("status", String, nullable=False),
    Column("params_json", Text, nullable=False),
    Column("progress_pct", Float, nullable=False, default=0),
    Column("metrics_json", Text),
    Column("error", Text),
    _in("status", BACKTEST_STATUSES),
)

backtest_trades = Table(
    "backtest_trades", metadata,
    Column("id", Integer, primary_key=True),
    Column("backtest_run_id", Integer, ForeignKey("backtest_runs.id"), nullable=False),
    Column("signal_id", Integer, ForeignKey("signals.id")),
    Column("trade_date", String, nullable=False),
    Column("symbol", String, nullable=False),
    Column("strategy", String, nullable=False),
    Column("direction", String, nullable=False),
    Column("entry_ts", String, nullable=False),
    Column("entry_price", Float, nullable=False),
    Column("exit_ts", String, nullable=False),
    Column("exit_price", Float, nullable=False),
    Column("exit_reason", String, nullable=False),
    Column("qty", Integer, nullable=False),
    Column("mfe_r", Float),
    Column("mae_r", Float),
    Column("gross_r", Float, nullable=False),
    Column("net_r", Float, nullable=False),
    Column("legs_json", Text),
)

health_events = Table(
    "health_events", metadata,
    Column("id", Integer, primary_key=True),
    Column("ts", String, nullable=False),
    Column("component", String, nullable=False),
    Column("level", String, nullable=False),
    Column("message", Text, nullable=False),
    _in("level", ("info", "warning", "error")),
)
