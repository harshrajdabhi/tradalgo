"""Simulated fills for backtest trades. Exits come from PositionManager events; this only prices them.

slippage_pct is in percent (0.05 = 0.05% per side, as in config.yaml) and is applied adversely to the entry and
to every exit leg. R unit = signal risk per share x qty. MFE/MAE are measured from the raw fill price; MAE <= 0.
"""
import itertools
from datetime import datetime

from tradalgo.config import CostsConfig
from tradalgo.engine.events import PositionEvent
from tradalgo.risk.costs import intraday_charges, split_sides
from tradalgo.risk.plan import TradePlan


class PaperBroker:
    def __init__(self, slippage_pct: float, costs: CostsConfig):
        self.slip = slippage_pct / 100
        self.costs = costs
        self.missed: list[dict] = []
        self._open: dict[int, dict] = {}
        self._ids = itertools.count(1)

    @staticmethod
    def fill_price(plan: TradePlan, next_open: float) -> float | None:
        return float(next_open) if plan.limit_low <= next_open <= plan.limit_high else None

    def miss(self, plan: TradePlan, signal_id: int, next_open: float | None) -> None:
        sig = plan.signal
        self.missed.append({"signal_id": signal_id, "trade_date": sig.ts.date().isoformat(), "symbol": sig.symbol,
                            "strategy": sig.strategy, "direction": sig.direction, "next_open": next_open,
                            "limit_low": plan.limit_low, "limit_high": plan.limit_high})

    def open(self, plan: TradePlan, signal_id: int, entry_ts: datetime, fill: float) -> int:
        trade_id = next(self._ids)
        self._open[trade_id] = {"plan": plan, "signal_id": signal_id, "entry_ts": entry_ts, "fill": float(fill),
                                "legs": [], "mfe_r": 0.0, "mae_r": 0.0}
        return trade_id

    def open_trade_ids(self) -> list[int]:
        return list(self._open)

    def symbol_of(self, trade_id: int) -> str:
        return self._open[trade_id]["plan"].signal.symbol

    def on_bar(self, trade_id: int, bar_start: datetime, high: float, low: float) -> None:
        t = self._open.get(trade_id)
        if t is None or bar_start < t["entry_ts"]:
            return
        sig = t["plan"].signal
        sign = 1 if sig.direction == "long" else -1
        best, worst = (high, low) if sign == 1 else (low, high)
        t["mfe_r"] = max(t["mfe_r"], sign * (best - t["fill"]) / sig.risk_per_share)
        t["mae_r"] = min(t["mae_r"], sign * (worst - t["fill"]) / sig.risk_per_share)

    def on_event(self, event: PositionEvent) -> dict | None:
        t = self._open.get(event.trade_id)
        if t is None or event.qty == 0:
            return None
        t["legs"].append({"kind": event.kind, "ts": event.ts, "price": float(event.price), "qty": event.qty})
        if sum(leg["qty"] for leg in t["legs"]) >= t["plan"].qty:
            return self._close(event.trade_id)
        return None

    def force_close(self, trade_id: int, ts: datetime, price: float, reason: str) -> dict:
        t = self._open[trade_id]
        remaining = t["plan"].qty - sum(leg["qty"] for leg in t["legs"])
        t["legs"].append({"kind": reason, "ts": ts, "price": float(price), "qty": remaining})
        return self._close(trade_id)

    def _close(self, trade_id: int) -> dict:
        t = self._open.pop(trade_id)
        plan, sig = t["plan"], t["plan"].signal
        sign = 1 if sig.direction == "long" else -1
        entry_slipped = t["fill"] * (1 + sign * self.slip)
        exits_slipped = [leg["price"] * (1 - sign * self.slip) for leg in t["legs"]]
        gross_pnl = sum(sign * (leg["price"] - t["fill"]) * leg["qty"] for leg in t["legs"])
        slipped_pnl = sum(sign * (px - entry_slipped) * leg["qty"] for px, leg in zip(exits_slipped, t["legs"]))
        unit = plan.qty * sig.risk_per_share
        net_rupees = slipped_pnl - self._charges(sig.direction, entry_slipped * plan.qty,
                                                 [px * leg["qty"] for px, leg in zip(exits_slipped, t["legs"])])
        charges_no_slip = self._charges(sig.direction, t["fill"] * plan.qty,
                                        [leg["price"] * leg["qty"] for leg in t["legs"]])
        return {
            "signal_id": t["signal_id"], "trade_date": sig.ts.date(), "symbol": sig.symbol,
            "strategy": sig.strategy, "direction": sig.direction, "regime": sig.regime.value,
            "entry_ts": t["entry_ts"], "entry_price": entry_slipped,
            "exit_ts": t["legs"][-1]["ts"],
            "exit_price": sum(px * leg["qty"] for px, leg in zip(exits_slipped, t["legs"])) / plan.qty,
            "exit_reason": t["legs"][-1]["kind"], "qty": plan.qty,
            "mfe_r": t["mfe_r"], "mae_r": t["mae_r"],
            "gross_r": gross_pnl / unit,
            "net_r_no_slippage": (gross_pnl - charges_no_slip) / unit,
            "net_r": net_rupees / unit,
            "net_rupees": net_rupees,
            "slippage_rupees": gross_pnl - slipped_pnl,
            "legs": t["legs"],
        }

    def _charges(self, direction: str, entry_value: float, exit_values: list[float]) -> float:
        return intraday_charges(*split_sides(direction, entry_value, exit_values), self.costs)
