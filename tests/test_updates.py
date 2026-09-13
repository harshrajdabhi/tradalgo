from datetime import datetime

import pytest
from sqlalchemy import insert, select

from tradalgo.clock import IST, FixedClock
from tradalgo.notify import updates
from tradalgo.storage import repo
from tradalgo.storage.db import init_db, make_engine
from tradalgo.storage.schema import alerts, health_events, signals, user_actions

NOW = datetime(2026, 9, 11, 9, 35, tzinfo=IST)
ALLOWED_CHAT = 999


@pytest.fixture
def engine(tmp_path):
    eng = make_engine(tmp_path / "t.db")
    init_db(eng)
    return eng


class FakeTelegramClient:
    def __init__(self, updates_batches):
        self.updates_batches = list(updates_batches)
        self.answered = []
        self.edited = []
        self.sent = []

    def get_updates(self, offset, timeout=0):
        if self.updates_batches:
            return self.updates_batches.pop(0)
        return []

    def answer_callback(self, callback_query_id, text=""):
        self.answered.append((callback_query_id, text))

    def edit_message(self, message_id, text, buttons=None):
        self.edited.append((message_id, text, buttons))

    def send_message(self, text, buttons=None):
        self.sent.append(text)
        return 1


def seed_entry_alert(engine, signal_id=None, message_id=100):
    alert_id = repo.enqueue_alert(engine, "entry:RELIANCE:orb:x", "entry", "ENTRY text", NOW, symbol="RELIANCE")
    repo.mark_alert_sent(engine, alert_id, message_id, NOW, 100)
    if signal_id is not None:
        from sqlalchemy import update
        with engine.begin() as conn:
            conn.execute(update(alerts).where(alerts.c.id == alert_id).values(signal_id=signal_id))
    return alert_id


def seed_signal(engine, entry_price=2500.0):
    with engine.begin() as conn:
        return conn.execute(insert(signals).values(
            ts=NOW.isoformat(), symbol="RELIANCE", strategy="orb", direction="long", regime="trend_up",
            entry=entry_price, stop_loss=2480.0, target_2r=2540.0, target_3r=2560.0,
            features_json="{}", mode="live",
        )).inserted_primary_key[0]


def status_text():
    return "All systems nominal"


@pytest.mark.parametrize("chat_id, allowed, expected", [
    (999, "999", True),
    (999, " 111 , 999 ", True),
    (111, "999,111", True),
    (222, "999,111", False),
    (999, 999, True),
])
def test_chat_allowed_accepts_comma_separated_ids(chat_id, allowed, expected):
    assert updates._chat_allowed(chat_id, allowed) is expected


def test_taken_callback_records_user_action_with_price(engine):
    signal_id = seed_signal(engine)
    alert_id = seed_entry_alert(engine, signal_id=signal_id)
    batch = [{
        "update_id": 1,
        "callback_query": {"id": "cb1", "data": f"taken:{alert_id}",
                            "message": {"chat": {"id": ALLOWED_CHAT}, "message_id": 100}},
    }]
    client = FakeTelegramClient([batch])
    from pathlib import Path
    next_offset = updates.process_updates(engine, client, FixedClock(NOW), 0, Path("/tmp"), ALLOWED_CHAT, status_text)
    assert next_offset == 2
    with engine.connect() as conn:
        row = conn.execute(select(user_actions).where(user_actions.c.alert_id == alert_id)).mappings().one()
    assert row["action"] == "taken"
    assert row["price"] == 2500.0
    assert client.answered == [("cb1", "Recorded")]
    assert len(client.edited) == 1
    assert "TAKEN" in client.edited[0][1]


def test_skip_callback_without_signal_has_null_price(engine):
    alert_id = seed_entry_alert(engine, signal_id=None)
    batch = [{
        "update_id": 1,
        "callback_query": {"id": "cb1", "data": f"skip:{alert_id}",
                            "message": {"chat": {"id": ALLOWED_CHAT}, "message_id": 100}},
    }]
    client = FakeTelegramClient([batch])
    from pathlib import Path
    updates.process_updates(engine, client, FixedClock(NOW), 0, Path("/tmp"), ALLOWED_CHAT, status_text)
    with engine.connect() as conn:
        row = conn.execute(select(user_actions).where(user_actions.c.alert_id == alert_id)).mappings().one()
    assert row["action"] == "skipped"
    assert row["price"] is None


def test_duplicate_callback_ignored_first_answer_wins(engine):
    alert_id = seed_entry_alert(engine)
    batch = [{
        "update_id": 1,
        "callback_query": {"id": "cb1", "data": f"taken:{alert_id}",
                            "message": {"chat": {"id": ALLOWED_CHAT}, "message_id": 100}},
    }, {
        "update_id": 2,
        "callback_query": {"id": "cb2", "data": f"skip:{alert_id}",
                            "message": {"chat": {"id": ALLOWED_CHAT}, "message_id": 100}},
    }]
    client = FakeTelegramClient([batch])
    from pathlib import Path
    updates.process_updates(engine, client, FixedClock(NOW), 0, Path("/tmp"), ALLOWED_CHAT, status_text)
    with engine.connect() as conn:
        rows = conn.execute(select(user_actions).where(user_actions.c.alert_id == alert_id)).mappings().all()
    assert len(rows) == 1
    assert rows[0]["action"] == "taken"
    assert client.answered[1] == ("cb2", "Already recorded")


def test_updates_from_disallowed_chat_are_ignored_but_offset_advances(engine):
    alert_id = seed_entry_alert(engine)
    batch = [{
        "update_id": 1,
        "callback_query": {"id": "cb1", "data": f"taken:{alert_id}",
                            "message": {"chat": {"id": 12345}, "message_id": 100}},
    }]
    client = FakeTelegramClient([batch])
    from pathlib import Path
    next_offset = updates.process_updates(engine, client, FixedClock(NOW), 0, Path("/tmp"), ALLOWED_CHAT, status_text)
    assert next_offset == 2
    with engine.connect() as conn:
        rows = conn.execute(select(user_actions)).mappings().all()
    assert rows == []


def test_kill_command_creates_kill_file_and_health_event(engine, tmp_path):
    batch = [{
        "update_id": 1,
        "message": {"chat": {"id": ALLOWED_CHAT}, "text": "/kill"},
    }]
    client = FakeTelegramClient([batch])
    updates.process_updates(engine, client, FixedClock(NOW), 0, tmp_path, ALLOWED_CHAT, status_text)
    assert (tmp_path / "KILL").exists()
    with engine.connect() as conn:
        rows = conn.execute(select(health_events)).mappings().all()
    assert len(rows) == 1
    assert rows[0]["component"] == "telegram"
    assert rows[0]["level"] == "warning"
    # I5: the kill switch stops NEW ENTRY alerts only; exits for open trades must keep coming
    assert client.sent == ["Kill switch on - no new entry alerts. Exit alerts for open trades keep coming."]


def test_kill_command_creates_the_data_dir_if_missing(engine, tmp_path):
    data_dir = tmp_path / "not-created-yet" / "data"
    batch = [{"update_id": 1, "message": {"chat": {"id": ALLOWED_CHAT}, "text": "/kill"}}]
    client = FakeTelegramClient([batch])
    updates.process_updates(engine, client, FixedClock(NOW), 0, data_dir, ALLOWED_CHAT, status_text)
    assert (data_dir / "KILL").exists() and len(client.sent) == 1


def test_resume_command_removes_kill_file(engine, tmp_path):
    (tmp_path / "KILL").touch()
    batch = [{
        "update_id": 1,
        "message": {"chat": {"id": ALLOWED_CHAT}, "text": "/resume"},
    }]
    client = FakeTelegramClient([batch])
    updates.process_updates(engine, client, FixedClock(NOW), 0, tmp_path, ALLOWED_CHAT, status_text)
    assert not (tmp_path / "KILL").exists()
    with engine.connect() as conn:
        rows = conn.execute(select(health_events)).mappings().all()
    assert len(rows) == 1


def test_status_command_replies_with_status_text(engine, tmp_path):
    batch = [{
        "update_id": 1,
        "message": {"chat": {"id": ALLOWED_CHAT}, "text": "/status"},
    }]
    client = FakeTelegramClient([batch])
    updates.process_updates(engine, client, FixedClock(NOW), 0, tmp_path, ALLOWED_CHAT, status_text)
    assert client.sent == ["All systems nominal"]


def test_no_updates_returns_same_offset(engine, tmp_path):
    client = FakeTelegramClient([[]])
    next_offset = updates.process_updates(engine, client, FixedClock(NOW), 7, tmp_path, ALLOWED_CHAT, status_text)
    assert next_offset == 7
