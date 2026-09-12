from datetime import timedelta

from tradalgo.config import CapitalConfig
from tradalgo.risk.limits import DailyRiskState, check_limits
from tradalgo.risk.plan import Rejection, TradePlan
from tradalgo.risk.sizing import effective_leverage, margin_required, position_qty
from tradalgo.strategies.base import Signal

NO_LEVEL_ROOM_R = 99.0  # finite so it stores cleanly in SQLite


def validate(
    signal: Signal,
    *,
    capital: float,
    capital_cfg: CapitalConfig,
    symbol_leverage: float | None,
    levels: list[float],
    limits_state: DailyRiskState,
    win_prob: float = 0.40,
    runner_avg_r: float = 2.0,
    min_room_r: float = 2.0,
    partial_fraction: float = 0.6,
    band_fraction_r: float = 0.1,
) -> TradePlan | Rejection:
    reason = check_limits(limits_state, signal, capital_cfg.max_trades_per_day, capital_cfg.daily_loss_limit_r)
    if reason:
        return Rejection(signal, reason)

    rps = signal.risk_per_share
    long = signal.direction == "long"
    band = band_fraction_r * rps
    limit_low, limit_high = (signal.entry, signal.entry + band) if long else (signal.entry - band, signal.entry)
    # size and measure room from the worst allowed manual fill so the 3% cap holds anywhere in the band
    worst = limit_high if long else limit_low
    leverage = effective_leverage(symbol_leverage, capital_cfg.max_leverage, capital_cfg.fallback_leverage)
    qty = position_qty(worst, signal.stop_loss, capital, capital_cfg.max_risk_pct, leverage)
    if qty == 0:
        return Rejection(signal, f"qty is 0 (capital {capital}, risk/share {rps:.2f}, leverage {leverage})")

    opposing = [lv for lv in levels if (lv >= signal.entry if long else lv <= signal.entry)]
    if opposing:
        nearest = min(opposing) if long else max(opposing)
        room_r = (nearest - worst) / rps if long else (worst - nearest) / rps
        if room_r < min_room_r:
            return Rejection(signal, f"insufficient room: level {nearest} is {room_r:.2f}R away (< {min_room_r}R)")
    else:
        room_r = NO_LEVEL_ROOM_R

    est_cost = capital_cfg.fixed_cost_rupees
    risk_rupees = qty * abs(worst - signal.stop_loss)
    cost_r = est_cost / (qty * rps)
    ev = win_prob * (partial_fraction * 2 + (1 - partial_fraction) * runner_avg_r) - (1 - win_prob) - cost_r
    if ev <= 0:
        return Rejection(signal, f"expected value {ev:.3f}R <= 0 after costs (cost {cost_r:.3f}R)")

    return TradePlan(
        signal=signal,
        qty=qty,
        leverage_used=leverage,
        margin_required=margin_required(qty, worst, leverage),
        risk_rupees=risk_rupees,
        target_2r=signal.target(2),
        target_3r=signal.target(3),
        est_cost=est_cost,
        room_to_level_r=room_r,
        expected_value_r=ev,
        limit_low=limit_low,
        limit_high=limit_high,
        # ts is the signal candle's start; it closed at +5, the next candle closes at +10
        valid_until=signal.ts + timedelta(minutes=10),
    )
