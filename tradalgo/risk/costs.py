"""Modeled FYERS equity-intraday charges in rupees. Rates live in config `costs:`; verify them against fyers.in/charges."""
from collections.abc import Sequence

from tradalgo.config import CostsConfig

CRORE = 1e7


def order_brokerage(value: float, cfg: CostsConfig) -> float:
    return min(cfg.brokerage_pct_per_order * value, cfg.brokerage_cap_per_order)


def intraday_charges(buy_orders: Sequence[float], sell_orders: Sequence[float], cfg: CostsConfig) -> float:
    """Each list holds the rupee value of every executed order on that side (a partial exit is its own order)."""
    buy, sell = sum(buy_orders), sum(sell_orders)
    turnover = buy + sell
    brokerage = sum(order_brokerage(v, cfg) for v in (*buy_orders, *sell_orders))
    exchange = cfg.exchange_txn_pct * turnover
    sebi = cfg.sebi_per_crore * turnover / CRORE
    ipft = cfg.ipft_per_crore * turnover / CRORE
    return (brokerage + exchange + sebi + ipft + cfg.stt_sell_pct * sell + cfg.stamp_buy_pct * buy
            + cfg.gst_pct * (brokerage + exchange + sebi))


def split_sides(direction: str, entry_value: float, exit_values: Sequence[float]) -> tuple[list[float], list[float]]:
    return ([entry_value], list(exit_values)) if direction == "long" else (list(exit_values), [entry_value])


def estimate_round_trip(entry: float, qty: int, direction: str, cfg: CostsConfig,
                        target_price: float | None = None) -> float:
    exit_price = entry if target_price is None else target_price
    return intraday_charges(*split_sides(direction, entry * qty, [exit_price * qty]), cfg)
