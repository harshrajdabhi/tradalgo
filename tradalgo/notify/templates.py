import html
from typing import TYPE_CHECKING

from tradalgo.clock import to_ist

if TYPE_CHECKING:
    from tradalgo.engine.events import PositionEvent
    from tradalgo.risk.plan import TradePlan

TELEGRAM_MAX_LEN = 4096
_REASON_TRUNCATE_SUFFIX = "..."

_EVENT_VERBS = {
    "stop_hit": "EXIT",
    "partial_exit": "SELL",
    "runner_exit": "EXIT",
    "hard_exit": "EXIT",
}


def _e(value) -> str:
    return html.escape(str(value))


def _r_label(r: float) -> str:
    """1.5 -> '1.5R', 2.0 -> '2R'; rounded to 2 dp so float noise from prices never shows."""
    return f"{round(r, 2):g}R"


def _truncate(text: str, limit: int = TELEGRAM_MAX_LEN) -> str:
    if len(text) <= limit:
        return text
    cut = limit - len(_REASON_TRUNCATE_SUFFIX)
    return text[:cut] + _REASON_TRUNCATE_SUFFIX


def shortlist_message(trade_date, rows: list[dict]) -> str:
    lines = [f"<b>Shortlist — {_e(trade_date)}</b>"]
    for row in rows:
        flag = " (demoted)" if row.get("demoted") else ""
        gap = row.get("gap_pct")
        gap_txt = f", gap {gap:+.2f}%" if gap is not None else ""
        lines.append(
            f"{row['rank']}. <b>{_e(row['symbol'])}</b> {_e(row['direction'])} "
            f"score={row['composite_score']:.1f}{gap_txt}{flag}\n"
            f"    {_e(row.get('reasons', ''))}"
        )
    return _truncate("\n".join(lines))


def entry_message(plan: "TradePlan", degraded: bool) -> str:
    s = plan.signal
    direction_label = "LONG" if s.direction == "long" else "SHORT"
    valid_until_txt = to_ist(plan.valid_until).strftime("%H:%M")
    # target_2r/target_3r hold the configured partial/runner levels, which need not be 2R/3R
    partial_r = abs(plan.target_2r - s.entry) / s.risk_per_share
    runner_r = abs(plan.target_3r - s.entry) / s.risk_per_share
    lines = [
        f"<b>ENTRY — {_e(s.symbol)} {direction_label}</b>",
        f"Strategy: {_e(s.strategy)}",
        f"Trigger/Entry: {plan.signal.entry:.2f}",
        f"Limit band: {plan.limit_low:.2f} – {plan.limit_high:.2f}",
        f"Stop loss / Invalidation: {s.stop_loss:.2f}",
        f"Partial target ({_r_label(partial_r)}): {plan.target_2r:.2f}   "
        f"Runner target ({_r_label(runner_r)}): {plan.target_3r:.2f}",
        f"R:R (to partial): {partial_r:.2f}",
        f"Qty: {plan.qty}",
        f"Margin required: ₹{plan.margin_required:.2f}   Leverage: {plan.leverage_used:.2f}x",
        f"Risk: ₹{plan.risk_rupees:.2f}   Est. cost: ₹{plan.est_cost:.2f}",
        f"Expected value: {plan.expected_value_r:.2f} R",
        f"Valid until: {valid_until_txt} IST",
        f"Reason: {_e(s.reason)}",
    ]
    if degraded:
        lines.append("⚠ DEGRADED DATA (yfinance fallback)")
    return _truncate("\n".join(lines))


def entry_buttons(alert_id: int) -> list[list[tuple[str, str]]]:
    return [[("✅ Taken", f"taken:{alert_id}"), ("❌ Skipped", f"skip:{alert_id}")]]


def position_event_message(event: "PositionEvent") -> str:
    time_txt = to_ist(event.ts).strftime("%H:%M")
    verb = _EVENT_VERBS.get(event.kind, "UPDATE")
    if event.kind == "trail_update":
        return _truncate(
            f"<b>TRAIL UPDATE — {_e(event.symbol)}</b>\n"
            f"New stop: {event.new_stop:.2f} (at {time_txt})"
        )
    reason = {
        "stop_hit": "stop hit",
        "partial_exit": f"partial exit at {_r_label(event.r_multiple)}",
        "runner_exit": f"runner exit at {_r_label(event.r_multiple)}",
        "hard_exit": "hard exit 15:00",
    }.get(event.kind, event.kind)
    return _truncate(
        f"<b>{verb} {event.qty} qty {_e(event.symbol)} now @ ~{event.price:.2f} ({reason})</b>\n"
        f"Time: {time_txt} IST   R: {event.r_multiple:.2f}"
    )


def expired_message(original_text: str) -> str:
    return _truncate(f"{original_text}\n\n<b>--- EXPIRED ---</b>")


def eod_summary_message(stats: dict) -> str:
    lines = [
        f"<b>EOD Summary — {_e(stats['trade_date'])}</b>",
        f"Alerts sent: {stats['alerts_sent']}",
        f"Taken: {stats['taken']}   Skipped: {stats['skipped']}",
        f"Closed trades: {stats['closed_trades']}",
        f"Net R: {stats['net_r']:.2f}   Net ₹: {stats['net_rupees']:.2f}",
    ]
    return _truncate("\n".join(lines))


def error_message(component: str, message: str) -> str:
    return _truncate(f"<b>ERROR — {_e(component)}</b>\n{_e(message)}")
