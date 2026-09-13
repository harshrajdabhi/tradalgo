"""Read-only diagnostics over a finished backtest run: pure pandas over backtest_trades/signals/decisions.

Never writes to the DB. `diagnose` groups net_r by several axes to separate entry-quality problems
(losers that never reached +0.5R) from exit-rule problems (winners stopped out after a big MFE) and
from cost drag (gross_r - net_r), plus fill rate and rejection-reason counts from the same run.
"""
import json
import re
from dataclasses import dataclass, field

import pandas as pd
from sqlalchemy import Engine, select

from tradalgo.clock import IST
from tradalgo.storage.schema import backtest_runs, backtest_trades, decisions, signals


@dataclass
class RunData:
    run_id: int
    trades: pd.DataFrame
    decisions: pd.DataFrame
    metrics: dict = field(default_factory=dict)


def load_run(engine: Engine, run_id: int) -> RunData:
    with engine.connect() as conn:
        run_row = conn.execute(select(backtest_runs.c.metrics_json).where(backtest_runs.c.id == run_id)).mappings().first()
        if run_row is None:
            raise ValueError(f"backtest run {run_id} does not exist")
        trade_rows = conn.execute(select(backtest_trades).where(backtest_trades.c.backtest_run_id == run_id)).mappings().all()
        signal_rows = conn.execute(select(signals).where(signals.c.backtest_run_id == run_id)).mappings().all()
        signal_ids = [r["id"] for r in signal_rows]
        decision_rows = []
        if signal_ids:
            decision_rows = conn.execute(
                select(decisions).where(decisions.c.signal_id.in_(signal_ids))
            ).mappings().all()

    metrics = json.loads(run_row["metrics_json"]) if run_row["metrics_json"] else {}

    sig_df = pd.DataFrame(signal_rows)
    trades = pd.DataFrame(trade_rows)
    if not trades.empty:
        trades["gross_minus_net_r"] = trades["gross_r"] - trades["net_r"]
        if not sig_df.empty:
            sig_lookup = sig_df.set_index("id")[["regime", "market_regime"]]
            trades = trades.join(sig_lookup, on="signal_id")
        else:
            trades["regime"] = None
            trades["market_regime"] = None
        entry_ts = pd.to_datetime(trades["entry_ts"], utc=True).dt.tz_convert(IST)
        trades["entry_hour"] = entry_ts.dt.hour

    dec_df = pd.DataFrame(decision_rows)
    if not dec_df.empty and not sig_df.empty:
        sig_meta = sig_df.set_index("id")[["strategy", "symbol", "ts"]]
        dec_df = dec_df.join(sig_meta, on="signal_id")

    return RunData(run_id=run_id, trades=trades, decisions=dec_df, metrics=metrics)


def _group_summary(df: pd.DataFrame, key: str) -> dict:
    out = {}
    if df.empty:
        return out
    for val, g in df.groupby(key):
        net = g["net_r"].tolist()
        n = len(net)
        out[str(val)] = {
            "trades": n,
            "win_rate": round(sum(r > 0 for r in net) / n, 4),
            "expectancy_r": round(sum(net) / n, 4),
            "avg_gross_r": round(g["gross_r"].mean(), 4),
            "avg_cost_slippage_drag_r": round(g["gross_minus_net_r"].mean(), 4),
        }
    return out


def _mfe_buckets(df: pd.DataFrame) -> dict:
    n = len(df)
    if n == 0:
        return {"count": 0, "pct_ge_0_5r": None, "pct_ge_1r": None, "pct_ge_2r": None}
    return {
        "count": n,
        "pct_ge_0_5r": round((df["mfe_r"] >= 0.5).sum() / n, 4),
        "pct_ge_1r": round((df["mfe_r"] >= 1.0).sum() / n, 4),
        "pct_ge_2r": round((df["mfe_r"] >= 2.0).sum() / n, 4),
    }


_NUM_RE = re.compile(r"-?\d+\.?\d*")
_SYMBOL_PAIR_RE = re.compile(r"on \w+/\w+")


def _reason_category(reason: str) -> str:
    """Rejection reasons carry per-signal detail (a price level, a capital figure, a symbol/strategy
    pair); strip that detail so counts aggregate meaningfully by cause rather than by exact text."""
    text = _SYMBOL_PAIR_RE.sub("on <symbol/strategy>", reason)
    text = _NUM_RE.sub("#", text)
    for sep in (":", "("):
        if sep in text:
            text = text.split(sep, 1)[0].strip()
    return text.strip()


_OVERALL_KEYS = ("trades", "win_rate", "expectancy_r", "expectancy_r_no_slippage", "profit_factor",
                 "max_drawdown_r", "net_r", "net_rupees", "missed_entries", "fill_rate")


def _overall_metrics(run: RunData, trades: pd.DataFrame) -> dict:
    """Headline metrics for the Overall section.

    Prefer the run's own stored metrics_json: it was computed by run_backtest from PaperBroker's raw
    per-trade records, which carry columns (net_r_no_slippage, net_rupees) that backtest_trades does
    not persist. Recomputing from backtest_trades alone can only use what that table has (net_r), so
    recomputing expectancy_r_no_slippage from it would silently equal expectancy_r — instead of that,
    fall back to a plain net_r summary and omit any metric that needs a column we don't have.
    """
    if run.metrics:
        return {k: run.metrics[k] for k in _OVERALL_KEYS if k in run.metrics}
    net = trades["net_r"].tolist() if not trades.empty else []
    n = len(net)
    if n == 0:
        return {"trades": 0, "win_rate": 0.0, "expectancy_r": 0.0}
    gains = sum(r for r in net if r > 0)
    losses = sum(r for r in net if r < 0)
    cum = peak = drawdown = 0.0
    for r in net:
        cum += r
        peak = max(peak, cum)
        drawdown = max(drawdown, peak - cum)
    return {
        "trades": n,
        "win_rate": round(sum(r > 0 for r in net) / n, 4),
        "expectancy_r": round(sum(net) / n, 4),
        "profit_factor": round(gains / abs(losses), 4) if losses < 0 else None,
        "max_drawdown_r": round(drawdown, 4),
        "net_r": round(sum(net), 4),
        # expectancy_r_no_slippage and net_rupees need columns backtest_trades doesn't have; omitted
        # rather than faked (backtest_trades has no net_r_no_slippage / net_rupees columns).
    }


def diagnose(run: RunData) -> dict:
    trades = run.trades
    report: dict = {"run_id": run.run_id}

    if trades.empty:
        report["overall"] = _overall_metrics(run, trades)
        report["by_strategy"] = {}
        report["by_regime"] = {}
        report["by_hour"] = {}
        report["by_direction"] = {}
        report["by_exit_reason"] = {}
        report["mfe_losers_by_strategy"] = {}
        report["mfe_winners_stop_after_partial_by_strategy"] = {}
        report["hard_exit_by_strategy"] = {}
        report["fill_rate_by_strategy"] = {}
        report["rejections"] = {}
        return report

    report["overall"] = _overall_metrics(run, trades)

    report["by_strategy"] = _group_summary(trades, "strategy")
    report["by_regime"] = _group_summary(trades, "regime")
    report["by_hour"] = _group_summary(trades, "entry_hour")
    report["by_direction"] = _group_summary(trades, "direction")
    report["by_exit_reason"] = _group_summary(trades, "exit_reason")

    losers = trades[trades["net_r"] < 0]
    mfe_losers = {}
    for strat, g in losers.groupby("strategy"):
        mfe_losers[strat] = _mfe_buckets(g)
    report["mfe_losers_by_strategy"] = mfe_losers

    winners_stop_after_partial = trades[(trades["net_r"] > 0) & (trades["exit_reason"] == "stop_hit")]
    mfe_winners = {}
    for strat, g in winners_stop_after_partial.groupby("strategy"):
        mfe_winners[strat] = {
            "count": len(g), "min_mfe_r": round(g["mfe_r"].min(), 4), "avg_mfe_r": round(g["mfe_r"].mean(), 4),
            "max_mfe_r": round(g["mfe_r"].max(), 4),
        }
    report["mfe_winners_stop_after_partial_by_strategy"] = mfe_winners

    hard_exit = trades[trades["exit_reason"] == "hard_exit"]
    hard_exit_by_strategy = {}
    for strat, g in hard_exit.groupby("strategy"):
        hard_exit_by_strategy[strat] = {"count": len(g), "avg_net_r": round(g["net_r"].mean(), 4)}
    report["hard_exit_by_strategy"] = hard_exit_by_strategy

    missed = run.metrics.get("missed", []) or []
    missed_by_strategy: dict[str, int] = {}
    for m in missed:
        missed_by_strategy[m["strategy"]] = missed_by_strategy.get(m["strategy"], 0) + 1
    fill_rate_by_strategy = {}
    trades_by_strategy = trades.groupby("strategy").size().to_dict()
    for strat in sorted(set(trades_by_strategy) | set(missed_by_strategy)):
        n_trades = trades_by_strategy.get(strat, 0)
        n_missed = missed_by_strategy.get(strat, 0)
        denom = n_trades + n_missed
        fill_rate_by_strategy[strat] = {
            "trades": n_trades, "missed": n_missed,
            "fill_rate": round(n_trades / denom, 4) if denom else None,
        }
    report["fill_rate_by_strategy"] = fill_rate_by_strategy

    rejections: dict[str, dict[str, int]] = {}
    dec = run.decisions
    if not dec.empty:
        rejected = dec[dec["accepted"] == 0].copy()
        rejected["reason_category"] = rejected["rejection_reason"].map(_reason_category)
        for (strat, reason), g in rejected.groupby(["strategy", "reason_category"]):
            rejections.setdefault(str(strat), {})[str(reason)] = len(g)
    report["rejections"] = rejections

    return report


def _fmt_pct(x) -> str:
    return "n/a" if x is None else f"{x:.1%}"


def _fmt_num(x, digits=4) -> str:
    return "n/a" if x is None else f"{x:.{digits}f}"


def _render_group_table(title: str, group: dict) -> list[str]:
    lines = [f"### {title}", "", "| key | trades | win_rate | expectancy_r | avg_gross_r | avg_cost_slippage_drag_r |",
             "|---|---|---|---|---|---|"]
    for key, s in group.items():
        lines.append(f"| {key} | {s['trades']} | {_fmt_pct(s['win_rate'])} | {_fmt_num(s['expectancy_r'])} | "
                     f"{_fmt_num(s['avg_gross_r'])} | {_fmt_num(s['avg_cost_slippage_drag_r'])} |")
    lines.append("")
    return lines


def render_markdown(report: dict) -> str:
    lines = [f"# Diagnostics report: run {report['run_id']}", ""]

    overall = report["overall"]
    lines += ["## Overall", "",
             f"- trades: {overall.get('trades', 0)}",
             f"- win_rate: {_fmt_pct(overall.get('win_rate'))}",
             f"- expectancy_r: {_fmt_num(overall.get('expectancy_r'))}",
             f"- expectancy_r_no_slippage: {_fmt_num(overall.get('expectancy_r_no_slippage'))}",
             f"- profit_factor: {overall.get('profit_factor')}",
             f"- max_drawdown_r: {overall.get('max_drawdown_r')}",
             ""]

    lines += _render_group_table("By strategy", report["by_strategy"])
    lines += _render_group_table("By regime", report["by_regime"])
    lines += _render_group_table("By hour of entry (IST)", report["by_hour"])
    lines += _render_group_table("By direction", report["by_direction"])
    lines += _render_group_table("By exit reason", report["by_exit_reason"])

    lines += ["### MFE analysis: losing trades (did they ever reach profit before stopping out?)", "",
             "| strategy | losers | %>=0.5R | %>=1R | %>=2R |", "|---|---|---|---|---|"]
    for strat, b in report["mfe_losers_by_strategy"].items():
        lines.append(f"| {strat} | {b['count']} | {_fmt_pct(b['pct_ge_0_5r'])} | {_fmt_pct(b['pct_ge_1r'])} | "
                     f"{_fmt_pct(b['pct_ge_2r'])} |")
    lines.append("")

    lines += ["### Winners that exited via stop_hit after a partial (MFE distribution)", "",
             "| strategy | count | min_mfe_r | avg_mfe_r | max_mfe_r |", "|---|---|---|---|---|"]
    for strat, b in report["mfe_winners_stop_after_partial_by_strategy"].items():
        lines.append(f"| {strat} | {b['count']} | {_fmt_num(b['min_mfe_r'])} | {_fmt_num(b['avg_mfe_r'])} | "
                     f"{_fmt_num(b['max_mfe_r'])} |")
    lines.append("")

    lines += ["### Hard-exit trades by strategy", "", "| strategy | count | avg_net_r |", "|---|---|---|"]
    for strat, b in report["hard_exit_by_strategy"].items():
        lines.append(f"| {strat} | {b['count']} | {_fmt_num(b['avg_net_r'])} |")
    lines.append("")

    lines += ["### Fill rate by strategy (missed entries)", "",
             "| strategy | trades | missed | fill_rate |", "|---|---|---|---|"]
    for strat, b in report["fill_rate_by_strategy"].items():
        lines.append(f"| {strat} | {b['trades']} | {b['missed']} | {_fmt_pct(b['fill_rate'])} |")
    lines.append("")

    lines += ["### Rejected signals by strategy x reason", "", "| strategy | reason | count |", "|---|---|---|"]
    for strat, reasons in report["rejections"].items():
        for reason, count in reasons.items():
            lines.append(f"| {strat} | {reason} | {count} |")
    lines.append("")

    lines += ["## What the numbers suggest", ""]
    suggestions = []
    for strat, b in report["mfe_losers_by_strategy"].items():
        if b["count"] and b["pct_ge_0_5r"] is not None and b["pct_ge_0_5r"] < 0.4:
            suggestions.append(f"- {strat}: {(1 - b['pct_ge_0_5r']):.0%} of losers never reached +0.5R "
                               f"before stopping -> likely an entry-quality problem, not an exit-rule problem.")
    for strat, s in report["by_strategy"].items():
        if s["avg_cost_slippage_drag_r"] and s["avg_cost_slippage_drag_r"] > 0.1:
            suggestions.append(f"- {strat}: cost + slippage drag averages {s['avg_cost_slippage_drag_r']:.2f}R "
                               "per trade.")
    total_trades = overall.get("trades", 0)
    hard_exit_total = sum(b["count"] for b in report["hard_exit_by_strategy"].values())
    if total_trades and hard_exit_total / total_trades > 0.3:
        suggestions.append(f"- {hard_exit_total / total_trades:.0%} of trades end at hard_exit "
                           "(time stop) rather than a target or stop -> exits are not resolving fast enough.")
    for strat, f in report["fill_rate_by_strategy"].items():
        if f["fill_rate"] is not None and f["fill_rate"] < 0.7:
            suggestions.append(f"- {strat}: fill rate is only {f['fill_rate']:.0%} -> many accepted plans "
                               "never get filled at the modeled entry band.")
    if not suggestions:
        suggestions.append("- No rule threshold was triggered by this run's numbers.")
    lines += suggestions
    lines.append("")

    return "\n".join(lines)
