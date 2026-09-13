"""Always-on worker: runs queued backtests and is the single Telegram sender (queued alerts, resends, expiry)."""
import json
import logging
import time
from datetime import datetime

from sqlalchemy import Engine, insert, select, update

from tradalgo.backtest.replay import BacktestCancelled, run_backtest
from tradalgo.clock import Clock, to_ist
from tradalgo.config import Settings
from tradalgo.data.base import ProviderError
from tradalgo.data.candle_cache import CandleCache
from tradalgo.data.universe import load_universe
from tradalgo.notify import sender
from tradalgo.notify.telegram import TelegramClient
from tradalgo.storage import repo
from tradalgo.storage.schema import backtest_runs, health_events

log = logging.getLogger(__name__)


class _CacheOnlyProvider:
    name = "cache-only"
    degraded = True

    def get_candles(self, symbol, resolution, start, end):
        raise ProviderError("backtests read the candle cache only; run `tradalgo backfill`")


def build_telegram_client(store) -> TelegramClient | None:
    token, chat_id = store.get("TELEGRAM_BOT_TOKEN"), store.get("TELEGRAM_CHAT_ID")
    return TelegramClient(token, chat_id) if token and chat_id else None


def _health(engine: Engine, now: datetime, level: str, message: str) -> None:
    with engine.begin() as conn:
        conn.execute(insert(health_events).values(ts=to_ist(now).isoformat(), component="worker", level=level,
                                                  message=message))


def _update_run(engine: Engine, run_id: int, **values) -> None:
    with engine.begin() as conn:
        conn.execute(update(backtest_runs).where(backtest_runs.c.id == run_id).values(**values))


def process_run(settings: Settings, engine: Engine, clock: Clock, run_id: int, *, runner=run_backtest,
                cache=None, universe=None) -> str:
    """Run one claimed backtest to a terminal status; never raises. Returns the final status.

    Cancel is checked between days, so a cancel requested during the final day still ends as 'done'.
    """
    def progress(pct: float) -> None:
        _update_run(engine, run_id, progress_pct=float(pct))

    def cancel_requested() -> bool:
        with engine.connect() as conn:
            status = conn.execute(select(backtest_runs.c.status).where(backtest_runs.c.id == run_id)).scalar()
        return status == "cancel_requested"

    try:
        with engine.connect() as conn:
            params = json.loads(conn.execute(
                select(backtest_runs.c.params_json).where(backtest_runs.c.id == run_id)).scalar())
        cache = cache or CandleCache(settings.paths.data_dir / "candles", _CacheOnlyProvider())
        universe = load_universe(settings.paths.static_dir) if universe is None else universe
        metrics = runner(settings, engine, params, run_id, cache, universe, progress, cancel_requested)
    except BacktestCancelled:
        _update_run(engine, run_id, status="cancelled", finished_at=to_ist(clock.now()).isoformat())
        return "cancelled"
    except Exception as exc:  # one bad run must not kill the worker
        log.exception("backtest run %s failed", run_id)
        _update_run(engine, run_id, status="failed", error=f"{type(exc).__name__}: {exc}",
                    finished_at=to_ist(clock.now()).isoformat())
        return "failed"
    _update_run(engine, run_id, status="done", progress_pct=100.0, metrics_json=json.dumps(metrics, allow_nan=False),
                error=None, finished_at=to_ist(clock.now()).isoformat())
    return "done"


def run_worker(settings: Settings, engine: Engine, clock: Clock, *, once: bool = False, sleep=time.sleep,
               telegram_client: TelegramClient | None = None, poll_seconds: float = 5, runner=run_backtest,
               cache=None, universe=None) -> None:
    """Poll forever. once=True: one sender pass, drain the backtest queue, return."""
    warned = False
    while True:
        if telegram_client is None:
            if not warned:
                _health(engine, clock.now(), "warning",
                        "Telegram not configured (TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID missing); alerts not sent")
                warned = True
        else:
            try:
                sender.send_pending(engine, telegram_client, clock)
                sender.expire_stale(engine, telegram_client, clock)
            except Exception as exc:  # a DB/network hiccup in the sender must not stop backtests
                log.exception("telegram sender pass failed")
                _health(engine, clock.now(), "error", f"telegram sender pass failed: {type(exc).__name__}: {exc}")

        run_id = repo.claim_next_backtest_run(engine, clock.now())
        if run_id is not None:
            process_run(settings, engine, clock, run_id, runner=runner, cache=cache, universe=universe)
            continue
        if once:
            return
        sleep(poll_seconds)
