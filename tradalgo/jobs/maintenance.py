"""Daily hardening chores: token-expiry reminder, log rotation, old-data pruning."""
from datetime import timedelta
from pathlib import Path

from sqlalchemy import Engine, delete, insert, select

from tradalgo.clock import Clock, to_ist
from tradalgo.config import Settings
from tradalgo.data.fyers_auth import refresh_token_expiry
from tradalgo.notify.sender import enqueue_text_alert
from tradalgo.storage.schema import backtest_runs, decisions, health_events, signals

PRUNABLE_BACKTEST_STATUSES = ("failed", "cancelled")
BACKTEST_ARTIFACT_KEEP_DAYS = 30


def _health(engine: Engine, now, level: str, component: str, message: str) -> None:
    with engine.begin() as conn:
        conn.execute(insert(health_events).values(
            ts=to_ist(now).isoformat(), component=component, level=level, message=message,
        ))


def token_expiry_reminder(engine: Engine, store, clock: Clock, days_before: int = 2) -> str | None:
    now = clock.now()
    today = to_ist(now).date()
    expiry = refresh_token_expiry(store)
    if expiry is not None and (expiry - today).days > days_before:
        return None

    expiry_label = expiry.isoformat() if expiry else "missing"
    if expiry is None:
        state = "missing"
    elif expiry <= today:
        state = "expired"
    else:
        state = "expiring"
    message = (
        f"FYERS refresh token {state} ({expiry_label}). Run `tradalgo login` to renew it."
    )
    enqueue_text_alert(engine, "health", f"token-expiry:{expiry_label}", message, now)
    _health(engine, now, "warning", "fyers", message)
    return message


def _numbered(path: Path, n: int) -> Path:
    return Path(f"{path}.{n}")


def rotate_logs(log_dir: Path, max_bytes: int = 5_000_000, keep: int = 5) -> list[Path]:
    log_dir = Path(log_dir)
    if not log_dir.exists():
        return []

    rotated = []
    for path in sorted(log_dir.glob("*.log")):
        if path.stat().st_size <= max_bytes:
            continue
        oldest = _numbered(path, keep)
        if oldest.exists():
            oldest.unlink()
        for n in range(keep - 1, 0, -1):
            src = _numbered(path, n)
            if src.exists():
                src.rename(_numbered(path, n + 1))
        dest = _numbered(path, 1)
        path.rename(dest)
        rotated.append(dest)
    return rotated


def prune_old_data(engine: Engine, clock: Clock, keep_days: int = 365) -> dict:
    now = clock.now()
    health_cutoff = to_ist(now - timedelta(days=keep_days)).isoformat()
    backtest_cutoff = to_ist(now - timedelta(days=BACKTEST_ARTIFACT_KEEP_DAYS)).isoformat()

    with engine.begin() as conn:
        run_ids = [
            r[0] for r in conn.execute(
                select(backtest_runs.c.id).where(
                    backtest_runs.c.status.in_(PRUNABLE_BACKTEST_STATUSES),
                    backtest_runs.c.created_at < backtest_cutoff,
                )
            ).all()
        ]
        signal_ids = []
        if run_ids:
            signal_ids = [
                r[0] for r in conn.execute(
                    select(signals.c.id).where(signals.c.backtest_run_id.in_(run_ids))
                ).all()
            ]

        decisions_deleted = 0
        signals_deleted = 0
        if signal_ids:
            decisions_deleted = conn.execute(
                delete(decisions).where(decisions.c.signal_id.in_(signal_ids))
            ).rowcount
            signals_deleted = conn.execute(
                delete(signals).where(signals.c.id.in_(signal_ids))
            ).rowcount

        health_deleted = conn.execute(
            delete(health_events).where(health_events.c.ts < health_cutoff)
        ).rowcount

    return {
        "health_events_deleted": health_deleted,
        "signals_deleted": signals_deleted,
        "decisions_deleted": decisions_deleted,
        "backtest_runs_pruned_from": len(run_ids),
    }


def run_maintenance(settings: Settings, engine: Engine, store, clock: Clock) -> dict:
    log_dir = settings.paths.data_dir / "logs"
    return {
        "token_expiry_message": token_expiry_reminder(engine, store, clock),
        "rotated_logs": rotate_logs(log_dir),
        "pruned": prune_old_data(engine, clock),
    }
