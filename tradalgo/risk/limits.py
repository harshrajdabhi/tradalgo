from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path

from tradalgo.strategies.base import Signal

EPS = 1e-9  # float sums like -1.2 + -0.8 must still trip the -2R limit


@dataclass(frozen=True)
class DailyRiskState:
    trade_date: date
    trades_taken: int = 0
    realized_r: float = 0.0
    open_trade_symbols: list[str] = field(default_factory=list)
    taken: list[tuple[str, str, bool, float | None]] = field(default_factory=list)  # (symbol, strategy, closed, net_r)


def check_limits(state: DailyRiskState, signal: Signal, max_trades_per_day: int, daily_loss_limit_r: float) -> str | None:
    """None = allowed.

    Reading of spec "only take the second if an independent valid setup appears" + plan row 13:
    independent = a symbol not already traded today (open or closed), which also excludes the same
    strategy on the same symbol. If an earlier trade closed at <= -1R, the next one must also use a
    different strategy than the losing one.
    """
    if signal.ts.date() != state.trade_date:
        return f"stale risk state: state date {state.trade_date} != signal date {signal.ts.date()}"
    if state.realized_r <= -daily_loss_limit_r + EPS:
        return f"daily loss limit reached ({state.realized_r:.2f}R <= -{daily_loss_limit_r}R)"
    if state.trades_taken >= max_trades_per_day:
        return f"max trades per day reached ({state.trades_taken}/{max_trades_per_day})"
    traded = {sym for sym, _, _, _ in state.taken} | set(state.open_trade_symbols)
    if signal.symbol in traded:
        return f"not independent: same symbol {signal.symbol} already traded today"
    for sym, strategy, closed, net_r in state.taken:
        if closed and net_r is not None and net_r <= -1.0 + EPS and strategy == signal.strategy:
            return f"after a -1R loss on {sym}/{strategy}, second trade needs a different strategy"
    return None


def register_entry(state: DailyRiskState, signal: Signal) -> DailyRiskState:
    return replace(
        state,
        trades_taken=state.trades_taken + 1,
        open_trade_symbols=[*state.open_trade_symbols, signal.symbol],
        taken=[*state.taken, (signal.symbol, signal.strategy, False, None)],
    )


def release_entry(state: DailyRiskState, symbol: str) -> DailyRiskState:
    """Undo a still-open registration for `symbol` (a provisional slot the user skipped or let expire)."""
    taken = list(state.taken)
    open_syms = list(state.open_trade_symbols)
    for i in range(len(taken) - 1, -1, -1):
        if taken[i][0] == symbol and not taken[i][2]:
            del taken[i]
            break
    else:
        return state
    if symbol in open_syms:
        open_syms.remove(symbol)
    return replace(state, trades_taken=max(0, state.trades_taken - 1), open_trade_symbols=open_syms, taken=taken)


def register_exit(state: DailyRiskState, symbol: str, net_r: float) -> DailyRiskState:
    taken = list(state.taken)
    for i, (sym, strategy, closed, _) in enumerate(taken):
        if sym == symbol and not closed:
            taken[i] = (sym, strategy, True, net_r)
            break
    open_syms = list(state.open_trade_symbols)
    if symbol in open_syms:
        open_syms.remove(symbol)
    return replace(state, realized_r=state.realized_r + net_r, open_trade_symbols=open_syms, taken=taken)


def kill_switch_active(data_dir: Path) -> bool:
    return (Path(data_dir) / "KILL").exists()
