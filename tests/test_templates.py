from datetime import datetime

from tradalgo.clock import IST
from tradalgo.engine.events import PositionEvent
from tradalgo.notify import templates
from tradalgo.risk.plan import TradePlan
from tradalgo.strategies.base import Regime, Signal

NOW = datetime(2026, 9, 11, 9, 35, tzinfo=IST)


def make_signal(direction="long", reason="ORB breakout with volume"):
    return Signal(
        symbol="RELIANCE", strategy="orb", direction=direction, ts=NOW,
        entry=2500.0, stop_loss=2480.0 if direction == "long" else 2520.0,
        regime=Regime.TREND_UP, market_regime=Regime.TREND_UP, counter_trend=False,
        reason=reason,
    )


def make_plan(signal=None, degraded=False):
    signal = signal or make_signal()
    return TradePlan(
        signal=signal, qty=10, leverage_used=3.0, margin_required=8333.33, risk_rupees=200.0,
        target_2r=2540.0, target_3r=2560.0, est_cost=50.0, room_to_level_r=2.5,
        expected_value_r=0.4, limit_low=2498.0, limit_high=2503.0,
        valid_until=datetime(2026, 9, 11, 9, 40, tzinfo=IST),
    )


def test_shortlist_message_contains_symbols_and_reasons():
    rows = [
        {"rank": 1, "symbol": "RELIANCE", "direction": "long", "composite_score": 82.5,
         "reasons": "strong trend & volume", "gap_pct": 0.8, "demoted": False},
        {"rank": 2, "symbol": "TCS", "direction": "short", "composite_score": 70.1,
         "reasons": "gap fade", "gap_pct": None, "demoted": True},
    ]
    msg = templates.shortlist_message("2026-09-11", rows)
    assert "RELIANCE" in msg
    assert "TCS" in msg
    assert "strong trend &amp; volume" in msg
    assert "demoted" in msg


def test_entry_message_includes_all_required_fields():
    plan = make_plan()
    msg = templates.entry_message(plan, degraded=False)
    for expected in [
        "RELIANCE", "LONG", "orb", "2500.00", "2480.00", "2540.00", "2560.00",
        "10", "8333.33", "3.00", "200.00", "50.00", "0.40", "09:40", "ORB breakout",
    ]:
        assert expected in msg, expected
    assert "DEGRADED" not in msg


def test_entry_message_shows_degraded_flag():
    msg = templates.entry_message(make_plan(), degraded=True)
    assert "DEGRADED DATA" in msg


def test_entry_message_escapes_html_in_reason():
    signal = make_signal(reason="breakout <script>above PDH & VWAP")
    msg = templates.entry_message(make_plan(signal=signal), degraded=False)
    assert "<script>" not in msg
    assert "&lt;script&gt;" in msg


def test_entry_message_under_telegram_limit_even_with_huge_reason():
    signal = make_signal(reason="x" * 10000)
    msg = templates.entry_message(make_plan(signal=signal), degraded=False)
    assert len(msg) <= templates.TELEGRAM_MAX_LEN


def test_entry_buttons_shape():
    buttons = templates.entry_buttons(42)
    assert buttons == [[("✅ Taken", "taken:42"), ("❌ Skipped", "skip:42")]]


def test_position_event_message_stop_hit_is_imperative():
    event = PositionEvent(
        kind="stop_hit", trade_id=1, symbol="SBIN", strategy="orb", ts=NOW,
        price=812.4, qty=12, new_stop=None, r_multiple=-1.0,
    )
    msg = templates.position_event_message(event)
    assert "EXIT" in msg
    assert "12" in msg
    assert "SBIN" in msg
    assert "812.40" in msg


def test_position_event_message_hard_exit_mentions_1500():
    event = PositionEvent(
        kind="hard_exit", trade_id=1, symbol="SBIN", strategy="orb", ts=NOW,
        price=812.4, qty=12, new_stop=None, r_multiple=0.5,
    )
    msg = templates.position_event_message(event)
    assert "15:00" in msg


def test_position_event_message_trail_update_shows_new_stop():
    event = PositionEvent(
        kind="trail_update", trade_id=1, symbol="SBIN", strategy="orb", ts=NOW,
        price=812.4, qty=0, new_stop=805.0, r_multiple=0.0,
    )
    msg = templates.position_event_message(event)
    assert "805.00" in msg


def test_expired_message_appends_expired_marker():
    msg = templates.expired_message("ENTRY - RELIANCE LONG ...")
    assert "EXPIRED" in msg
    assert "ENTRY - RELIANCE LONG" in msg


def test_eod_summary_message_contains_stats():
    stats = {
        "trade_date": "2026-09-11", "alerts_sent": 4, "taken": 2, "skipped": 2,
        "closed_trades": 2, "net_r": 1.2, "net_rupees": 480.0,
    }
    msg = templates.eod_summary_message(stats)
    assert "2026-09-11" in msg
    assert "1.20" in msg
    assert "480.00" in msg


def test_error_message_escapes_and_includes_component():
    msg = templates.error_message("fyers_provider", "connection <reset>")
    assert "fyers_provider" in msg
    assert "&lt;reset&gt;" in msg
