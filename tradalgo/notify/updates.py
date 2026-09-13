from pathlib import Path
from typing import Callable

from sqlalchemy import Engine, insert, select, update

from tradalgo.clock import Clock, to_ist
from tradalgo.notify.telegram import TelegramClient
from tradalgo.storage.schema import alerts, health_events, signals, user_actions


def _record_action(engine: Engine, alert_id: int, action: str, ts) -> bool:
    """Returns True if this is the first action recorded for the alert."""
    with engine.connect() as conn:
        existing = conn.execute(
            select(user_actions.c.id).where(user_actions.c.alert_id == alert_id).limit(1)
        ).first()
    if existing is not None:
        return False
    with engine.connect() as conn:
        alert_row = conn.execute(select(alerts).where(alerts.c.id == alert_id)).mappings().first()
    price = None
    if alert_row is not None and alert_row["signal_id"] is not None:
        with engine.connect() as conn:
            sig = conn.execute(
                select(signals.c.entry).where(signals.c.id == alert_row["signal_id"])
            ).first()
        if sig is not None:
            price = sig[0]
    with engine.begin() as conn:
        conn.execute(insert(user_actions).values(
            alert_id=alert_id, action=action, price=price, ts=to_ist(ts).isoformat(),
        ))
    return True


def _health_event(engine: Engine, component: str, level: str, message: str, ts) -> None:
    with engine.begin() as conn:
        conn.execute(insert(health_events).values(
            ts=to_ist(ts).isoformat(), component=component, level=level, message=message,
        ))


def process_updates(engine: Engine, client: TelegramClient, clock: Clock, offset: int, data_dir: Path,
                     allowed_chat_id: str | int, status_text: Callable[[], str]) -> int:
    updates = client.get_updates(offset, timeout=0)
    next_offset = offset

    for upd in updates:
        next_offset = max(next_offset, upd["update_id"] + 1)

        callback = upd.get("callback_query")
        message = upd.get("message")

        if callback is not None:
            from_chat = callback.get("message", {}).get("chat", {}).get("id")
            if str(from_chat) != str(allowed_chat_id):
                continue
            data = callback.get("data", "")
            if ":" not in data:
                client.answer_callback(callback["id"])
                continue
            action_key, _, alert_id_str = data.partition(":")
            if action_key not in ("taken", "skip"):
                client.answer_callback(callback["id"])
                continue
            alert_id = int(alert_id_str)
            action = "taken" if action_key == "taken" else "skipped"
            now = clock.now()
            is_first = _record_action(engine, alert_id, action, now)
            client.answer_callback(callback["id"], text="Recorded" if is_first else "Already recorded")
            if is_first:
                with engine.connect() as conn:
                    alert_row = conn.execute(select(alerts).where(alerts.c.id == alert_id)).mappings().first()
                if alert_row is not None and alert_row["telegram_message_id"] is not None:
                    label = "TAKEN" if action == "taken" else "SKIPPED"
                    time_txt = to_ist(now).strftime("%H:%M")
                    new_text = f"{alert_row['text']}\n\n— marked {label} at {time_txt}"
                    client.edit_message(alert_row["telegram_message_id"], new_text)
            continue

        if message is not None:
            chat_id = message.get("chat", {}).get("id")
            if str(chat_id) != str(allowed_chat_id):
                continue
            text = (message.get("text") or "").strip()
            now = clock.now()
            if text == "/kill":
                Path(data_dir).mkdir(parents=True, exist_ok=True)
                (data_dir / "KILL").touch()
                _health_event(engine, "telegram", "warning", "kill switch activated via Telegram", now)
                client.send_message("Kill switch on - no new entry alerts. "
                                    "Exit alerts for open trades keep coming.")
            elif text == "/resume":
                kill_path = data_dir / "KILL"
                if kill_path.exists():
                    kill_path.unlink()
                _health_event(engine, "telegram", "info", "kill switch deactivated via Telegram", now)
                client.send_message("Resumed. Alerts active.")
            elif text == "/status":
                client.send_message(status_text())
            continue

    return next_offset
