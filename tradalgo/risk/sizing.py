import math


def effective_leverage(symbol_leverage: float | None, max_leverage: float, fallback_leverage: float) -> float:
    return float(min(fallback_leverage if symbol_leverage is None or symbol_leverage <= 0 else symbol_leverage, max_leverage))


def position_qty(entry: float, stop_loss: float, capital: float, max_risk_pct: float, leverage: float) -> int:
    risk = abs(entry - stop_loss)
    if risk <= 0 or entry <= 0:
        return 0
    risk_qty = math.floor(capital * max_risk_pct / risk)
    leverage_qty = math.floor(capital * leverage / entry)
    return max(0, min(risk_qty, leverage_qty))


def margin_required(qty: int, entry: float, leverage: float) -> float:
    return qty * entry / leverage
