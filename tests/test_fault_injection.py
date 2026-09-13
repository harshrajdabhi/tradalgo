"""M9 fault-injection tests: FYERS down, token expired, Telegram down, worker crash, DB busy. All offline."""
from datetime import date, datetime, timedelta

import pandas as pd
import pytest
from sqlalchemy import insert, select

from tradalgo.clock import IST, FixedClock
from tradalgo.data.base import FallbackProvider, ProviderError
from tradalgo.data.candle_cache import CandleCache
from tradalgo.data.fyers_auth import AuthError, get_access_token
from tradalgo.jobs.backtest_worker import process_run, run_worker
from tradalgo.jobs.maintenance import token_expiry_reminder
from tradalgo.notify import sender
from tradalgo.notify.telegram import TelegramClient, TelegramError
from tradalgo.storage import repo
from tradalgo.storage.db import init_db, make_engine
from tradalgo.storage.schema import alerts, backtest_runs

NOW = datetime(2026, 9, 13, 10, 0, tzinfo=IST)


@pytest.fixture
def engine(tmp_path):
    eng = make_engine(tmp_path / "t.db")
    init_db(eng)
    return eng


# ---------------------------------------------------------------- FYERS down

def daily_frame(start: date, end: date) -> pd.DataFrame:
    days = pd.date_range(start, end, freq="D", tz="Asia/Kolkata")
    return pd.DataFrame({"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 100.0}, index=days)


class AlwaysDownPrimary:
    name = "fyers"
    degraded = False

    def __init__(self, exc_factory):
        self.exc_factory = exc_factory
        self.calls = 0

    def get_candles(self, symbol, resolution, start, end):
        self.calls += 1
        raise self.exc_factory()


class FakeYFinance:
    name = "yfinance"
    degraded = True

    def get_candles(self, symbol, resolution, start, end):
        return daily_frame(start, end)


@pytest.mark.parametrize("exc_factory", [lambda: ProviderError("fyers unreachable"),
                                          lambda: ConnectionError("network down")])
def test_fyers_down_falls_back_to_yfinance_and_marks_degraded(exc_factory):
    fallback_calls = []
    primary = AlwaysDownPrimary(exc_factory)
    provider = FallbackProvider(primary, FakeYFinance(), on_fallback=fallback_calls.append)

    df = provider.get_candles("SBIN", "1d", date(2026, 9, 1), date(2026, 9, 2))
    df2 = provider.get_candles("RELIANCE", "1d", date(2026, 9, 1), date(2026, 9, 2))

    assert provider.degraded and provider.name == "yfinance"
    assert len(df) == 2 and len(df2) == 2
    assert primary.calls == 2
    assert len(fallback_calls) == 2  # once per failing request


def test_fyers_down_degraded_data_is_never_persisted_to_cache(tmp_path):
    primary = AlwaysDownPrimary(lambda: ProviderError("down"))
    provider = FallbackProvider(primary, FakeYFinance())
    cache = CandleCache(tmp_path, provider)

    cache.get("SBIN", "1d", date(2026, 9, 1), date(2026, 9, 5))

    assert not (tmp_path / "1d" / "SBIN.parquet").exists()
    # a later, healthy fetch on a fresh cache instance still has to hit the network again
    assert len(cache.load("SBIN", "1d")) == 0


# ------------------------------------------------------------ token expired

class MemoryStore(dict):
    def get(self, name, default=None):
        return super().get(name, default)

    def set(self, name, value):
        self[name] = value


def creds(**extra):
    return MemoryStore(FYERS_APP_ID="APP", FYERS_SECRET_KEY="SECRET", FYERS_PIN="1234", **extra)


def test_expired_refresh_token_raises_auth_error_pointing_to_login():
    store = creds(FYERS_REFRESH_TOKEN="ref", FYERS_REFRESH_TOKEN_ISSUED="2026-08-01")
    with pytest.raises(AuthError, match="tradalgo login"):
        get_access_token(store, date(2026, 9, 13), post=lambda *a, **kw: (_ for _ in ()).throw(AssertionError))


def test_token_expiry_reminder_enqueues_exactly_one_alert_across_repeated_calls(engine):
    store = creds(FYERS_REFRESH_TOKEN="ref", FYERS_REFRESH_TOKEN_ISSUED="2026-08-01")
    for _ in range(5):
        msg = token_expiry_reminder(engine, store, FixedClock(NOW))
        assert msg is not None and "tradalgo login" in msg
    with engine.connect() as conn:
        assert len(conn.execute(select(alerts)).all()) == 1


# ------------------------------------------------------------- Telegram down

class FlakyTelegramClient:
    def __init__(self, fail=True):
        self.fail = fail
        self.sent = []

    def send_message(self, text, buttons=None):
        if self.fail:
            raise TelegramError("HTTP error calling sendMessage")
        self.sent.append(text)
        return 1

    def edit_message(self, message_id, text, buttons=None):
        pass


def test_telegram_down_marks_failed_and_retries_capped_at_max_attempts(engine):
    repo.enqueue_alert(engine, "k1", "entry", "hello", NOW)
    down = FlakyTelegramClient(fail=True)
    clock = FixedClock(NOW)

    for _ in range(5):
        sender.send_pending(engine, down, clock, max_attempts=3)

    with engine.connect() as conn:
        row = conn.execute(select(alerts)).mappings().one()
    assert row["status"] == "failed"
    assert row["attempts"] == 3  # never exceeds max_attempts
    assert "token" not in (row["last_error"] or "").lower() or "SECRET" not in (row["last_error"] or "")


def test_telegram_down_error_never_leaks_token(engine):
    import requests

    class DeadSession:
        def post(self, url, json, timeout):
            # requests/urllib3 embed the full request URL (with the bot token) in this text
            raise requests.ConnectionError(f"Failed to establish a new connection: {url}")

    client = TelegramClient(token="SECRET_TOKEN", chat_id="123", http=DeadSession())
    repo.enqueue_alert(engine, "k1", "entry", "hello", NOW)
    sender.send_pending(engine, client, FixedClock(NOW), max_attempts=3)
    with engine.connect() as conn:
        row = conn.execute(select(alerts)).mappings().one()
    assert row["status"] == "failed"
    assert "SECRET_TOKEN" not in row["last_error"]


def test_telegram_recovers_and_delivers_queued_alerts_once_healthy(engine):
    repo.enqueue_alert(engine, "k1", "entry", "hello", NOW)
    down = FlakyTelegramClient(fail=True)
    sender.send_pending(engine, down, FixedClock(NOW), max_attempts=3)

    healthy = FlakyTelegramClient(fail=False)
    counts = sender.send_pending(engine, healthy, FixedClock(NOW + timedelta(minutes=1)), max_attempts=3)

    assert counts["sent"] == 1
    assert healthy.sent == ["hello"]
    with engine.connect() as conn:
        row = conn.execute(select(alerts)).mappings().one()
    assert row["status"] == "sent"


# ---------------------------------------------------------- worker resilience

def test_worker_records_failure_and_still_processes_next_queued_run(engine, settings):
    bad = repo.enqueue_backtest_run(engine, {}, NOW)
    good = repo.enqueue_backtest_run(engine, {}, NOW)

    def runner(settings_, engine_, params, run_id, *rest):
        if run_id == bad:
            raise RuntimeError("candle cache exploded")
        return {"trades": 0, "win_rate": 0.0, "expectancy_r": 0.0, "expectancy_r_no_slippage": 0.0,
                "profit_factor": None, "max_drawdown_r": 0.0, "net_r": 0.0, "net_rupees": 0.0,
                "by_strategy": {}, "by_regime": {}}

    run_worker(settings, engine, FixedClock(NOW), once=True, runner=runner, cache=object(), universe=[])

    with engine.connect() as conn:
        bad_row = conn.execute(select(backtest_runs).where(backtest_runs.c.id == bad)).mappings().one()
        good_row = conn.execute(select(backtest_runs).where(backtest_runs.c.id == good)).mappings().one()
    assert bad_row["status"] == "failed" and "candle cache exploded" in bad_row["error"]
    assert good_row["status"] == "done"


# ----------------------------------------------------------------- DB busy

def test_reader_keeps_working_while_writer_holds_a_transaction(tmp_path):
    db_path = tmp_path / "shared.db"
    writer_engine = make_engine(db_path)
    init_db(writer_engine)
    reader_engine = make_engine(db_path)

    repo.enqueue_backtest_run(writer_engine, {"a": 1}, NOW)

    with writer_engine.connect() as write_conn:
        write_conn.execute(insert(backtest_runs).values(
            created_at="2026-09-13T10:00:00+05:30", status="queued", params_json="{}", progress_pct=0,
        ))
        # WAL mode: readers on a separate connection see the last committed snapshot
        # while this write transaction (not yet committed) is open.
        with reader_engine.connect() as read_conn:
            rows = read_conn.execute(select(backtest_runs.c.id)).all()
        assert len(rows) == 1
        write_conn.commit()

    with reader_engine.connect() as read_conn:
        rows = read_conn.execute(select(backtest_runs.c.id)).all()
    assert len(rows) == 2
