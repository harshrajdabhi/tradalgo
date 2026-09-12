from datetime import datetime, timedelta

import pytest
from sqlalchemy import insert, select

from tradalgo.clock import IST, FixedClock
from tradalgo.engine.events import PositionEvent
from tradalgo.notify import sender
from tradalgo.notify.telegram import TelegramError
from tradalgo.risk.plan import TradePlan
from tradalgo.storage import repo
from tradalgo.storage.db import init_db, make_engine
from tradalgo.storage.schema import alerts, signals, user_actions
from tradalgo.strategies.base import Regime, Signal

NOW = datetime(2026, 9, 11, 9, 35, tzinfo=IST)


@pytest.fixture
def engine(tmp_path):
    eng = make_engine(tmp_path / "t.db")
    init_db(eng)
    return eng


class FakeTelegramClient:
    def __init__(self, fail_ids=None, message_id_start=100):
        self.fail_ids = fail_ids or set()
        self.sent = []
        self.edited = []
        self._next_id = message_id_start

    def send_message(self, text, buttons=None):
        if text in self.fail_ids:
            raise TelegramError("boom")
        self.sent.append((text, buttons))
        self._next_id += 1
        return self._next_id

    def edit_message(self, message_id, text, buttons=None):
        self.edited.append((message_id, text, buttons))


def make_plan(entry_ts=NOW, valid_until=None):
    signal = Signal(
        symbol="RELIANCE", strategy="orb", direction="long", ts=entry_ts,
        entry=2500.0, stop_loss=2480.0, regime=Regime.TREND_UP, market_regime=Regime.TREND_UP,
        counter_trend=False, reason="orb breakout",
    )
    return TradePlan(
        signal=signal, qty=10, leverage_used=3.0, margin_required=8333.33, risk_rupees=200.0,
        target_2r=2540.0, target_3r=2560.0, est_cost=50.0, room_to_level_r=2.5,
        expected_value_r=0.4, limit_low=2498.0, limit_high=2503.0,
        valid_until=valid_until or (entry_ts + timedelta(minutes=5)),
    )


def test_enqueue_entry_alert_sets_valid_until_and_signal_id(engine):
    plan = make_plan()
    alert_id = sender.enqueue_entry_alert(engine, plan, signal_id=None, degraded=False, now=NOW)
    assert alert_id is not None
    with engine.connect() as conn:
        row = conn.execute(select(alerts).where(alerts.c.id == alert_id)).mappings().one()
    assert row["alert_type"] == "entry"
    assert row["valid_until"] == plan.valid_until.isoformat()
    assert row["status"] == "queued"


def test_enqueue_entry_alert_dedups(engine):
    plan = make_plan()
    first = sender.enqueue_entry_alert(engine, plan, None, False, NOW)
    second = sender.enqueue_entry_alert(engine, plan, None, False, NOW)
    assert first is not None
    assert second is None


def test_send_pending_marks_sent_and_records_latency(engine):
    plan = make_plan()
    alert_id = sender.enqueue_entry_alert(engine, plan, None, False, NOW)
    client = FakeTelegramClient()
    clock = FixedClock(NOW + timedelta(seconds=2))
    counts = sender.send_pending(engine, client, clock)
    assert counts == {"sent": 1, "failed": 0}
    with engine.connect() as conn:
        row = conn.execute(select(alerts).where(alerts.c.id == alert_id)).mappings().one()
    assert row["status"] == "sent"
    assert row["latency_ms"] == 2000
    assert row["telegram_message_id"] is not None
    # entry alerts get Taken/Skipped buttons
    text, buttons = client.sent[0]
    assert buttons == [[("✅ Taken", f"taken:{alert_id}"), ("❌ Skipped", f"skip:{alert_id}")]]


def test_send_pending_one_failure_does_not_block_others(engine):
    plan1 = make_plan(entry_ts=NOW)
    plan2 = make_plan(entry_ts=NOW + timedelta(minutes=5))
    id1 = sender.enqueue_entry_alert(engine, plan1, None, False, NOW)
    id2 = sender.enqueue_entry_alert(engine, plan2, None, False, NOW)
    client = FakeTelegramClient()
    # make the first alert's text fail
    with engine.connect() as conn:
        text1 = conn.execute(select(alerts.c.text).where(alerts.c.id == id1)).scalar()
    client.fail_ids = {text1}
    clock = FixedClock(NOW)
    counts = sender.send_pending(engine, client, clock)
    assert counts == {"sent": 1, "failed": 1}
    with engine.connect() as conn:
        row1 = conn.execute(select(alerts).where(alerts.c.id == id1)).mappings().one()
        row2 = conn.execute(select(alerts).where(alerts.c.id == id2)).mappings().one()
    assert row1["status"] == "failed"
    assert row1["last_error"] == "boom"
    assert row2["status"] == "sent"


def test_send_pending_retries_failed_below_max_attempts(engine):
    plan = make_plan()
    alert_id = sender.enqueue_entry_alert(engine, plan, None, False, NOW)
    repo.mark_alert_failed(engine, alert_id, "prior error")
    client = FakeTelegramClient()
    clock = FixedClock(NOW)
    counts = sender.send_pending(engine, client, clock, max_attempts=3)
    assert counts["sent"] == 1


def test_send_pending_stops_retrying_after_max_attempts(engine):
    plan = make_plan()
    alert_id = sender.enqueue_entry_alert(engine, plan, None, False, NOW)
    repo.mark_alert_failed(engine, alert_id, "e1")
    repo.mark_alert_failed(engine, alert_id, "e2")
    repo.mark_alert_failed(engine, alert_id, "e3")
    client = FakeTelegramClient()
    clock = FixedClock(NOW)
    counts = sender.send_pending(engine, client, clock, max_attempts=3)
    assert counts == {"sent": 0, "failed": 0}


def test_send_pending_persists_no_token_in_last_error_on_http_failure(engine):
    import requests

    from tradalgo.notify.telegram import TelegramClient

    class LeakySession:
        def post(self, url, json, timeout):
            raise requests.ConnectionError(
                "HTTPSConnectionPool(host='api.telegram.org', port=443): "
                "Max retries exceeded with url: /botTOP_SECRET_TOKEN/sendMessage (Caused by ...)"
            )

    plan = make_plan()
    alert_id = sender.enqueue_entry_alert(engine, plan, None, False, NOW)
    client = TelegramClient(token="TOP_SECRET_TOKEN", chat_id="123", http=LeakySession())
    clock = FixedClock(NOW)
    counts = sender.send_pending(engine, client, clock)
    assert counts == {"sent": 0, "failed": 1}
    with engine.connect() as conn:
        row = conn.execute(select(alerts).where(alerts.c.id == alert_id)).mappings().one()
    assert row["status"] == "failed"
    assert "TOP_SECRET_TOKEN" not in (row["last_error"] or "")


def test_enqueue_event_alert(engine):
    event = PositionEvent(
        kind="stop_hit", trade_id=1, symbol="SBIN", strategy="orb", ts=NOW,
        price=812.4, qty=12, new_stop=None, r_multiple=-1.0,
    )
    alert_id = sender.enqueue_event_alert(engine, event, NOW)
    assert alert_id is not None
    with engine.connect() as conn:
        row = conn.execute(select(alerts).where(alerts.c.id == alert_id)).mappings().one()
    assert row["alert_type"] == "event"
    assert "SBIN" in row["text"]


def test_enqueue_text_alert(engine):
    alert_id = sender.enqueue_text_alert(engine, "eod", "eod:2026-09-11", "EOD summary text", NOW)
    assert alert_id is not None


def test_expire_stale_edits_message_and_sets_expired(engine):
    plan = make_plan(entry_ts=NOW, valid_until=NOW + timedelta(minutes=5))
    alert_id = sender.enqueue_entry_alert(engine, plan, None, False, NOW)
    client = FakeTelegramClient()
    send_clock = FixedClock(NOW)
    sender.send_pending(engine, client, send_clock)

    expire_clock = FixedClock(NOW + timedelta(minutes=10))
    count = sender.expire_stale(engine, client, expire_clock)
    assert count == 1
    with engine.connect() as conn:
        row = conn.execute(select(alerts).where(alerts.c.id == alert_id)).mappings().one()
    assert row["status"] == "expired"
    assert len(client.edited) == 1
    message_id, text, buttons = client.edited[0]
    assert buttons == []
    assert "EXPIRED" in text


def test_expire_stale_skips_alerts_with_user_action(engine):
    plan = make_plan(entry_ts=NOW, valid_until=NOW + timedelta(minutes=5))
    alert_id = sender.enqueue_entry_alert(engine, plan, None, False, NOW)
    client = FakeTelegramClient()
    sender.send_pending(engine, client, FixedClock(NOW))
    with engine.begin() as conn:
        conn.execute(insert(user_actions).values(
            alert_id=alert_id, action="taken", price=2500.0, ts=NOW.isoformat(),
        ))
    count = sender.expire_stale(engine, client, FixedClock(NOW + timedelta(minutes=10)))
    assert count == 0
    with engine.connect() as conn:
        row = conn.execute(select(alerts).where(alerts.c.id == alert_id)).mappings().one()
    assert row["status"] == "sent"


def test_expire_stale_ignores_not_yet_expired(engine):
    plan = make_plan(entry_ts=NOW, valid_until=NOW + timedelta(minutes=30))
    alert_id = sender.enqueue_entry_alert(engine, plan, None, False, NOW)
    client = FakeTelegramClient()
    sender.send_pending(engine, client, FixedClock(NOW))
    count = sender.expire_stale(engine, client, FixedClock(NOW + timedelta(minutes=5)))
    assert count == 0
