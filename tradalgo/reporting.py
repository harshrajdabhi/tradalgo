"""Pure DB-reading report builders (no Streamlit, no side effects)."""
import html
import json
from datetime import date, datetime, timedelta

from sqlalchemy import Engine, and_, select

from tradalgo.clock import IST, to_ist
from tradalgo.storage.schema import alerts, backtest_runs, decisions, paper_trades, signals, user_actions

DIVERGENCE_R_THRESHOLD = 0.5
DIVERGENCE_MIN_LIVE_TRADES = 10


def _iso_date(value: str) -> date:
    return datetime.fromisoformat(value).astimezone(IST).date()


def _week_bounds(end_date: date, weeks: int) -> tuple[date, date]:
    """A rolling `weeks * 7`-day trailing window ending on `end_date` (inclusive), IST dates.

    Deliberately not an ISO Monday-start calendar week: `weekly_report` is meant to be callable
    for any `end_date` (e.g. "as of today") and still cover exactly `weeks` full weeks of data,
    which a fixed Mon-Sun bucket wouldn't do for a mid-week `end_date`.
    """
    return end_date - timedelta(days=7 * weeks - 1), end_date


def _round(x: float) -> float:
    return round(float(x), 4)


def _net_rupees(trade: dict) -> float:
    return float(trade["net_r"]) * float(trade["risk_rupees"] or 0.0)


def _bucket_summary(trades: list[dict]) -> dict:
    closed = [t for t in trades if t["net_r"] is not None]
    n = len(closed)
    net_rupees = sum(_net_rupees(t) for t in closed)
    if n == 0:
        return {"count": 0, "win_rate": 0.0, "expectancy_r": 0.0, "net_rupees": _round(net_rupees)}
    wins = sum(1 for t in closed if t["net_r"] > 0)
    return {
        "count": n,
        "win_rate": _round(wins / n),
        "expectancy_r": _round(sum(t["net_r"] for t in closed) / n),
        "net_rupees": _round(net_rupees),
    }


def _fetch_week_trades(engine: Engine, start: date, end: date) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(
            select(paper_trades, signals.c.strategy, decisions.c.risk_rupees)
            .join(signals, paper_trades.c.signal_id == signals.c.id)
            .outerjoin(decisions, decisions.c.signal_id == signals.c.id)
        ).mappings().all()
    out = []
    for row in rows:
        d = _iso_date(row["entry_ts"])
        if start <= d <= end:
            out.append(dict(row))
    return out


def _fetch_week_alerts(engine: Engine, start: date, end: date) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(select(alerts)).mappings().all()
    return [dict(r) for r in rows if start <= _iso_date(r["created_at"]) <= end]


def weekly_report(engine: Engine, end_date: date, weeks: int = 1) -> dict:
    """Report over a rolling `weeks * 7`-day trailing window ending on `end_date` (inclusive),
    in IST dates — see `_week_bounds`. Not an ISO Monday-start calendar week.
    """
    start, end = _week_bounds(end_date, weeks)
    trades = _fetch_week_trades(engine, start, end)
    taken = [t for t in trades if t["taken_by_user"]]
    not_taken = [t for t in trades if not t["taken_by_user"]]

    curve = []
    cum = 0.0
    for t in sorted([t for t in taken if t["net_r"] is not None], key=lambda t: t["exit_ts"] or t["entry_ts"]):
        cum += t["net_r"]
        curve.append({"date": _iso_date(t["exit_ts"] or t["entry_ts"]).isoformat(), "cum_r": _round(cum)})

    week_alerts = _fetch_week_alerts(engine, start, end)
    alert_counts = {"sent": 0, "failed": 0, "expired": 0}
    for a in week_alerts:
        if a["status"] in alert_counts:
            alert_counts[a["status"]] += 1

    entry_alerts = [a for a in week_alerts if a["alert_type"] == "entry" and a["status"] in ("sent", "expired")]
    entry_alert_ids = {a["id"] for a in entry_alerts}
    with engine.connect() as conn:
        action_rows = conn.execute(
            select(user_actions).where(user_actions.c.action.in_(("taken", "skipped")))
        ).mappings().all()
    responded = sum(1 for r in action_rows if r["alert_id"] in entry_alert_ids)
    response_rate = _round(responded / len(entry_alerts)) if entry_alerts else 0.0

    by_strategy: dict[str, list[dict]] = {}
    for t in trades:
        by_strategy.setdefault(t["strategy"], []).append(t)
    per_strategy = {k: _bucket_summary(v) for k, v in sorted(by_strategy.items())}

    return {
        "week_start": start.isoformat(),
        "week_end": end.isoformat(),
        "taken": _bucket_summary(taken),
        "not_taken": _bucket_summary(not_taken),
        "weekly_r_curve": curve,
        "alerts": alert_counts,
        "response_rate": response_rate,
        "by_strategy": per_strategy,
    }


def _latest_completed_run(engine: Engine) -> dict | None:
    with engine.connect() as conn:
        row = conn.execute(
            select(backtest_runs).where(backtest_runs.c.status == "done")
            .order_by(backtest_runs.c.id.desc()).limit(1)
        ).mappings().first()
    return dict(row) if row else None


def _all_time_live_by_strategy(engine: Engine) -> dict[str, dict]:
    with engine.connect() as conn:
        rows = conn.execute(
            select(paper_trades, signals.c.strategy, decisions.c.risk_rupees)
            .join(signals, paper_trades.c.signal_id == signals.c.id)
            .outerjoin(decisions, decisions.c.signal_id == signals.c.id)
            .where(and_(paper_trades.c.taken_by_user == 1, paper_trades.c.net_r.isnot(None)))
        ).mappings().all()
    by_strategy: dict[str, list[dict]] = {}
    for r in rows:
        by_strategy.setdefault(r["strategy"], []).append(dict(r))
    return {k: _bucket_summary(v) for k, v in by_strategy.items()}


def live_vs_backtest(engine: Engine, backtest_run_id: int | None = None) -> list[dict]:
    if backtest_run_id is not None:
        with engine.connect() as conn:
            row = conn.execute(
                select(backtest_runs).where(backtest_runs.c.id == backtest_run_id)
            ).mappings().first()
        run = dict(row) if row else None
    else:
        run = _latest_completed_run(engine)
    if run is None or not run.get("metrics_json"):
        return []

    bt_by_strategy = json.loads(run["metrics_json"]).get("by_strategy", {})
    live_by_strategy = _all_time_live_by_strategy(engine)

    result = []
    for strategy in sorted(set(bt_by_strategy) | set(live_by_strategy)):
        bt = bt_by_strategy.get(strategy, {"trades": 0, "win_rate": 0.0, "expectancy_r": 0.0})
        live = live_by_strategy.get(strategy, {"count": 0, "win_rate": 0.0, "expectancy_r": 0.0})
        divergence = _round(live["expectancy_r"] - bt["expectancy_r"])
        flagged = abs(divergence) > DIVERGENCE_R_THRESHOLD and live["count"] >= DIVERGENCE_MIN_LIVE_TRADES
        result.append({
            "strategy": strategy,
            "backtest_run_id": run["id"],
            "live_trades": live["count"],
            "live_expectancy_r": live["expectancy_r"],
            "live_win_rate": live["win_rate"],
            "backtest_trades": bt["trades"],
            "backtest_expectancy_r": bt["expectancy_r"],
            "backtest_win_rate": bt["win_rate"],
            "divergence_r": divergence,
            "flagged": flagged,
        })
    return result


def _e(value) -> str:
    return html.escape(str(value))


def format_report_text(report: dict, divergence: list[dict]) -> str:
    lines = [
        f"<b>Weekly Report — {_e(report['week_start'])} to {_e(report['week_end'])}</b>",
        f"Taken: {report['taken']['count']} (win {report['taken']['win_rate']:.0%}, "
        f"exp {report['taken']['expectancy_r']:.2f}R, ₹{report['taken']['net_rupees']:.2f})",
        f"Not taken: {report['not_taken']['count']} (win {report['not_taken']['win_rate']:.0%}, "
        f"exp {report['not_taken']['expectancy_r']:.2f}R)",
        f"Alerts — sent {report['alerts']['sent']}, failed {report['alerts']['failed']}, "
        f"expired {report['alerts']['expired']}",
        f"Response rate: {report['response_rate']:.0%}",
    ]
    if report["weekly_r_curve"]:
        lines.append(f"Cumulative R: {report['weekly_r_curve'][-1]['cum_r']:.2f}")
    if report["by_strategy"]:
        lines.append("<b>By strategy</b>")
        for name, s in report["by_strategy"].items():
            lines.append(f"  {_e(name)}: {s['count']} trades, exp {s['expectancy_r']:.2f}R")
    if divergence:
        lines.append("<b>Live vs backtest</b>")
        for d in divergence:
            flag = " ⚠" if d["flagged"] else ""
            lines.append(
                f"  {_e(d['strategy'])}: live {d['live_expectancy_r']:.2f}R "
                f"vs bt {d['backtest_expectancy_r']:.2f}R (Δ{d['divergence_r']:+.2f}R){flag}"
            )
    return "\n".join(lines)
