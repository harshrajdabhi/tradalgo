"""Modeled FYERS equity-intraday charges in rupees. Rates live in config `costs:`; verify them against fyers.in/charges."""
from tradalgo.config import CostsConfig

CRORE = 1e7


def order_brokerage(value: float, cfg: CostsConfig) -> float:
    return min(cfg.brokerage_pct_per_order * value, cfg.brokerage_cap_per_order)


def intraday_charges(buy_value: float, sell_value: float, cfg: CostsConfig, orders: int = 2) -> float:
    turnover = buy_value + sell_value
    # turnover is split evenly across the executed orders; a partial exit is one extra sell order
    brokerage = orders * order_brokerage(turnover / orders, cfg) if orders else 0.0
    exchange = cfg.exchange_txn_pct * turnover
    sebi = cfg.sebi_per_crore * turnover / CRORE
    ipft = cfg.ipft_per_crore * turnover / CRORE
    stt = cfg.stt_sell_pct * sell_value
    stamp = cfg.stamp_buy_pct * buy_value
    return brokerage + exchange + sebi + ipft + stt + stamp + cfg.gst_pct * (brokerage + exchange + sebi)


def estimate_round_trip(entry: float, qty: int, direction: str, cfg: CostsConfig,
                        target_price: float | None = None) -> float:
    entry_value = entry * qty
    exit_value = (entry if target_price is None else target_price) * qty
    buy, sell = (entry_value, exit_value) if direction == "long" else (exit_value, entry_value)
    return intraday_charges(buy, sell, cfg)
