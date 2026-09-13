"""Pure metrics over completed trade records (dicts with net_r, net_r_no_slippage, net_rupees, strategy, regime).

win = net_r > 0. profit_factor = sum of winning net_r / |sum of losing net_r|; None when there are no losing
trades (undefined, and JSON has no infinity). max_drawdown_r = largest peak-to-trough fall of cumulative net_r
(peak starts at 0), reported as a positive number. Trades must be passed in chronological order.
"""
from collections import defaultdict


def _round(x: float) -> float:
    return round(float(x), 4)


def _summary(net: list[float]) -> dict:
    n = len(net)
    if n == 0:
        return {"trades": 0, "win_rate": 0.0, "expectancy_r": 0.0}
    return {"trades": n, "win_rate": _round(sum(r > 0 for r in net) / n), "expectancy_r": _round(sum(net) / n)}


def _breakdown(trades: list[dict], key: str) -> dict:
    groups: dict[str, list[float]] = defaultdict(list)
    for t in trades:
        groups[str(t[key])].append(t["net_r"])
    return {k: _summary(v) for k, v in sorted(groups.items())}


def compute_metrics(trades: list[dict], missed: list[dict] = ()) -> dict:
    """missed = accepted plans whose next open fell outside the limit band; fill_rate is None with no accepted plans."""
    net = [float(t["net_r"]) for t in trades]
    no_slip = [float(t["net_r_no_slippage"]) for t in trades]
    gains = sum(r for r in net if r > 0)
    losses = sum(r for r in net if r < 0)
    cum = peak = drawdown = 0.0
    for r in net:
        cum += r
        peak = max(peak, cum)
        drawdown = max(drawdown, peak - cum)
    summary = _summary(net)
    return {
        **summary,
        "expectancy_r_no_slippage": _round(sum(no_slip) / len(no_slip)) if no_slip else 0.0,
        "profit_factor": _round(gains / abs(losses)) if losses < 0 else None,
        "max_drawdown_r": _round(drawdown),
        "net_r": _round(sum(net)),
        "net_rupees": _round(sum(float(t["net_rupees"]) for t in trades)),
        "by_strategy": _breakdown(trades, "strategy"),
        "by_regime": _breakdown(trades, "regime"),
        "missed_entries": len(missed),
        "fill_rate": _round(len(trades) / (len(trades) + len(missed))) if trades or missed else None,
        "missed": list(missed),
    }
