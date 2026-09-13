import json
from datetime import date, datetime

from sqlalchemy import Engine, insert, select, update
from sqlalchemy.exc import IntegrityError

from tradalgo.clock import to_ist
from tradalgo.storage.schema import alerts, backtest_runs, job_runs


def _iso(dt: datetime) -> str:
    return to_ist(dt).isoformat()


def start_job_run(engine: Engine, job: str, now: datetime) -> int:
    with engine.begin() as conn:
        return conn.execute(insert(job_runs).values(
            job=job, run_date=to_ist(now).date().isoformat(), started_at=_iso(now), status="running",
        )).inserted_primary_key[0]


def finish_job_run(engine: Engine, run_id: int, now: datetime, error: str | None = None) -> None:
    with engine.begin() as conn:
        conn.execute(update(job_runs).where(job_runs.c.id == run_id).values(
            finished_at=_iso(now), status="failed" if error else "succeeded", error=error,
        ))


def has_job_succeeded_on(engine: Engine, job: str, day: date) -> bool:
    with engine.connect() as conn:
        return conn.execute(select(job_runs.c.id).where(
            job_runs.c.job == job,
            job_runs.c.run_date == day.isoformat(),
            job_runs.c.status == "succeeded",
        )).first() is not None


def enqueue_alert(engine: Engine, dedup_key: str, alert_type: str, text: str, now: datetime,
                  symbol: str | None = None) -> int | None:
    """Returns the new alert id, or None if an alert with this dedup_key already exists."""
    try:
        with engine.begin() as conn:
            return conn.execute(insert(alerts).values(
                dedup_key=dedup_key, alert_type=alert_type, symbol=symbol, text=text,
                status="queued", created_at=_iso(now), attempts=0,
            )).inserted_primary_key[0]
    except IntegrityError:
        return None


def mark_alert_sent(engine: Engine, alert_id: int, message_id: int, now: datetime, latency_ms: int) -> None:
    with engine.begin() as conn:
        conn.execute(update(alerts).where(alerts.c.id == alert_id).values(
            status="sent", telegram_message_id=message_id, sent_at=_iso(now),
            latency_ms=latency_ms, attempts=alerts.c.attempts + 1, last_error=None,
        ))


def mark_alert_failed(engine: Engine, alert_id: int, error: str) -> None:
    with engine.begin() as conn:
        conn.execute(update(alerts).where(alerts.c.id == alert_id).values(
            status="failed", attempts=alerts.c.attempts + 1, last_error=error,
        ))


def enqueue_backtest_run(engine: Engine, params: dict, now: datetime) -> int:
    with engine.begin() as conn:
        return conn.execute(insert(backtest_runs).values(
            created_at=_iso(now), status="queued", params_json=json.dumps(params), progress_pct=0,
        )).inserted_primary_key[0]


def claim_backtest_run(engine: Engine, run_id: int, now: datetime) -> bool:
    """Atomically claims exactly this run (not the FIFO head); True iff it was queued and is now running."""
    with engine.begin() as conn:
        claimed = conn.execute(update(backtest_runs).where(
            backtest_runs.c.id == run_id, backtest_runs.c.status == "queued",
        ).values(status="running", started_at=_iso(now)))
        return claimed.rowcount == 1


def claim_next_backtest_run(engine: Engine, now: datetime) -> int | None:
    """Atomically moves the oldest queued run to 'running'; returns its id or None."""
    with engine.begin() as conn:
        run_id = conn.execute(
            select(backtest_runs.c.id).where(backtest_runs.c.status == "queued")
            .order_by(backtest_runs.c.id).limit(1)
        ).scalar()
        if run_id is None:
            return None
        claimed = conn.execute(update(backtest_runs).where(
            backtest_runs.c.id == run_id, backtest_runs.c.status == "queued",
        ).values(status="running", started_at=_iso(now)))
        return run_id if claimed.rowcount == 1 else None
