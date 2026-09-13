from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Engine, and_, or_, select, update

from tradalgo.clock import Clock, to_ist
from tradalgo.notify.telegram import TelegramClient, TelegramError
from tradalgo.notify.templates import entry_buttons, entry_message, expired_message, position_event_message
from tradalgo.storage import repo
from tradalgo.storage.schema import alerts, user_actions

if TYPE_CHECKING:
    from tradalgo.engine.events import PositionEvent
    from tradalgo.risk.plan import TradePlan


def enqueue_entry_alert(engine: Engine, plan: "TradePlan", signal_id: int | None, degraded: bool,
                         now: datetime) -> int | None:
    signal = plan.signal
    dedup_key = f"entry:{signal.symbol}:{signal.strategy}:{signal.ts.isoformat()}"
    text = entry_message(plan, degraded)
    alert_id = repo.enqueue_alert(engine, dedup_key, "entry", text, now, symbol=signal.symbol)
    if alert_id is None:
        return None
    with engine.begin() as conn:
        conn.execute(update(alerts).where(alerts.c.id == alert_id).values(
            valid_until=to_ist(plan.valid_until).isoformat(), signal_id=signal_id,
        ))
    return alert_id


ONCE_ONLY_EVENTS = ("stop_hit", "partial_exit", "runner_exit", "hard_exit")


def enqueue_event_alert(engine: Engine, event: "PositionEvent", now: datetime) -> int | None:
    # each once-only leg happens at most once per trade, so a replay at a different ts must not re-alert
    dedup_key = (f"{event.kind}:{event.trade_id}" if event.kind in ONCE_ONLY_EVENTS
                 else f"{event.kind}:{event.trade_id}:{event.ts.isoformat()}")
    text = position_event_message(event)
    return repo.enqueue_alert(engine, dedup_key, "event", text, now, symbol=event.symbol)


def enqueue_text_alert(engine: Engine, alert_type: str, dedup_key: str, text: str, now: datetime) -> int | None:
    return repo.enqueue_alert(engine, dedup_key, alert_type, text, now)


def send_pending(engine: Engine, client: TelegramClient, clock: Clock, max_attempts: int = 3) -> dict:
    counts = {"sent": 0, "failed": 0}
    now = clock.now()
    with engine.connect() as conn:
        rows = conn.execute(
            select(alerts).where(
                or_(
                    alerts.c.status == "queued",
                    and_(alerts.c.status == "failed", alerts.c.attempts < max_attempts),
                )
            ).order_by(alerts.c.id)
        ).mappings().all()

    for row in rows:
        buttons = entry_buttons(row["id"]) if row["alert_type"] == "entry" else None
        try:
            message_id = client.send_message(row["text"], buttons=buttons)
        except TelegramError as exc:
            repo.mark_alert_failed(engine, row["id"], str(exc))
            counts["failed"] += 1
            continue
        send_now = clock.now()
        created = to_ist(datetime.fromisoformat(row["created_at"]))
        latency_ms = int((to_ist(send_now) - created).total_seconds() * 1000)
        repo.mark_alert_sent(engine, row["id"], message_id, send_now, latency_ms)
        counts["sent"] += 1
    return counts


def expire_stale(engine: Engine, client: TelegramClient, clock: Clock) -> int:
    now_iso = to_ist(clock.now()).isoformat()
    expired = 0
    with engine.connect() as conn:
        rows = conn.execute(
            select(alerts).where(
                alerts.c.alert_type == "entry",
                alerts.c.status == "sent",
                alerts.c.valid_until.isnot(None),
                alerts.c.valid_until < now_iso,
            )
        ).mappings().all()

    for row in rows:
        with engine.connect() as conn:
            has_action = conn.execute(
                select(user_actions.c.id).where(user_actions.c.alert_id == row["id"]).limit(1)
            ).first() is not None
        if has_action:
            continue
        try:
            client.edit_message(row["telegram_message_id"], expired_message(row["text"]), buttons=[])
        except TelegramError:
            continue
        with engine.begin() as conn:
            conn.execute(update(alerts).where(alerts.c.id == row["id"]).values(status="expired"))
        expired += 1
    return expired
