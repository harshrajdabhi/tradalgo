import argparse
import json
import os
import subprocess
import sys
import time
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import insert, select, update

from tradalgo.clock import MarketCalendar, SystemClock, load_holidays, to_ist
from tradalgo.config import KeyringStore, load_settings
from tradalgo.data.base import INDEX_SYMBOL, FallbackProvider
from tradalgo.data.candle_cache import CandleCache
from tradalgo.data.yfinance_provider import YFinanceProvider
from tradalgo.indicators.core import atr
from tradalgo.notify.sender import enqueue_text_alert
from tradalgo.notify.templates import shortlist_message
from tradalgo.screener.preopen import annotate_preopen
from tradalgo.screener.run import run_screen
from tradalgo.storage.db import init_db, make_engine
from tradalgo.storage.repo import finish_job_run, has_job_succeeded_on, start_job_run
from tradalgo.storage.schema import backtest_runs, health_events, shortlist

# Injection points for tests: monkeypatch these instead of hitting the network or keychain.
clock_factory = SystemClock
store_factory = KeyringStore
run_subprocess = subprocess.run
backtest_poll_sleep = time.sleep
backtest_poll_seconds = 2


def cmd_init(settings, args) -> int:
    settings.paths.data_dir.mkdir(parents=True, exist_ok=True)
    init_db(make_engine(settings.paths.db_path))
    print(f"Initialised database at {settings.paths.db_path}")
    return 0


def cmd_login(settings, args) -> int:
    from tradalgo.data.fyers_auth import auth_url, login_with_auth_code, refresh_token_expiry, require

    store = store_factory()
    print("Open this URL, log in, then copy the auth_code parameter from the redirect URL:")
    print(auth_url(require(store, "FYERS_APP_ID"), require(store, "FYERS_SECRET_KEY"), settings.fyers.redirect_uri))
    login_with_auth_code(store, input("auth_code: ").strip(), clock_factory().now().date())
    print(f"FYERS tokens stored in keychain; refresh token valid until {refresh_token_expiry(store)}")
    return 0


def cmd_backfill(settings, args) -> int:
    from fyers_apiv3.fyersModel import FyersModel

    from tradalgo.data.base import ProviderError
    from tradalgo.data.fyers_auth import get_access_token, require
    from tradalgo.data.fyers_provider import FyersProvider
    from tradalgo.data.universe import load_universe, refresh_constituents

    store = store_factory()
    today = clock_factory().now().date()
    start = today - timedelta(days=round(30.5 * args.months))
    logs = settings.paths.data_dir / "logs"
    logs.mkdir(parents=True, exist_ok=True)

    for problem in refresh_constituents(settings.paths.static_dir):
        print(f"warning: {problem}", file=sys.stderr)
    client = FyersModel(client_id=require(store, "FYERS_APP_ID"), token=get_access_token(store, today),
                        is_async=False, log_path=str(logs))
    cache = CandleCache(settings.paths.data_dir / "candles", FyersProvider(client))
    symbols = [c.symbol for c in load_universe(settings.paths.static_dir)] + [INDEX_SYMBOL]

    failures = 0
    for i, symbol in enumerate(symbols, 1):
        for resolution in ("1d", "5m"):
            try:
                n = len(cache.get(symbol, resolution, start, today))
                print(f"[{i}/{len(symbols)}] {symbol} {resolution}: {n} candles")
            except ProviderError as exc:
                failures += 1
                print(f"[{i}/{len(symbols)}] {symbol} {resolution}: FAILED {exc}", file=sys.stderr)
    return 1 if failures else 0


def _resolve_trade_date(args, clock) -> date:
    return date.fromisoformat(args.date) if args.date else clock.now().date()


def _last_trading_day(calendar, d: date, max_lookback: int = 14) -> date:
    for _ in range(max_lookback):
        d -= timedelta(days=1)
        if calendar.is_trading_day(d):
            return d
    raise ValueError(f"no trading day found within {max_lookback} days before {d}")


def _record_health_event(engine, now, component: str, message: str) -> None:
    print(f"warning: {message}", file=sys.stderr)
    with engine.begin() as conn:
        conn.execute(insert(health_events).values(
            ts=to_ist(now).isoformat(), component=component, level="warning", message=message))


def build_screen_provider(settings, store, today, on_fallback):
    """FYERS (with yfinance fallback) for daily candles; falls back to yfinance-only if FYERS auth fails."""
    from fyers_apiv3.fyersModel import FyersModel

    from tradalgo.data.fyers_auth import get_access_token, require
    from tradalgo.data.fyers_provider import FyersProvider

    try:
        logs = settings.paths.data_dir / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        client = FyersModel(client_id=require(store, "FYERS_APP_ID"), token=get_access_token(store, today),
                            is_async=False, log_path=str(logs))
        return FallbackProvider(FyersProvider(client), YFinanceProvider(), on_fallback=on_fallback)
    except Exception as exc:
        on_fallback(f"FYERS unavailable ({exc}); using yfinance only")
        return YFinanceProvider()


def build_fyers_quote_provider(settings, store, today):
    """A bare FyersProvider for pre-open quotes. Raises if FYERS auth/login is unavailable."""
    from fyers_apiv3.fyersModel import FyersModel

    from tradalgo.data.fyers_auth import get_access_token, require
    from tradalgo.data.fyers_provider import FyersProvider

    logs = settings.paths.data_dir / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    client = FyersModel(client_id=require(store, "FYERS_APP_ID"), token=get_access_token(store, today),
                        is_async=False, log_path=str(logs))
    return FyersProvider(client)


def cmd_screen(settings, args) -> int:
    from tradalgo.data.universe import load_universe, refresh_constituents

    clock = clock_factory()
    store = store_factory()
    engine = make_engine(settings.paths.db_path)
    now = clock.now()
    trade_date = _resolve_trade_date(args, clock)

    calendar = MarketCalendar(settings.market, load_holidays(settings.paths.static_dir, trade_date.year))
    if not calendar.is_trading_day(trade_date):
        if not args.test:
            print(f"{trade_date} is not a trading day; skipping screen")
            return 0
        requested = trade_date
        trade_date = _last_trading_day(calendar, trade_date)
        print(f"--test: {requested} is not a trading day; screening as of the last trading day "
              f"{trade_date} instead (no Telegram alert will be sent)")
    if not args.test and not args.force and has_job_succeeded_on(engine, "screen", trade_date):
        print(f"screen already succeeded for {trade_date}; use --force to rerun")
        return 0

    for problem in refresh_constituents(settings.paths.static_dir):
        print(f"warning: {problem}", file=sys.stderr)
    universe = load_universe(settings.paths.static_dir)

    def on_fallback(message):
        _record_health_event(engine, now, "data", message)

    # This try/except covers only steps before run_screen: run_screen owns the "screen" job_runs
    # row itself (start_job_run/finish_job_run), so recording a failure here too would double it up.
    try:
        provider = build_screen_provider(settings, store, trade_date, on_fallback)
        cache = CandleCache(settings.paths.data_dir / "candles", provider)
        start = trade_date - timedelta(days=400)
        symbols = [c.symbol for c in universe]
        daily_by_symbol = {s: cache.get(s, "1d", start, trade_date - timedelta(days=1)) for s in symbols}
        index_daily = cache.get(INDEX_SYMBOL, "1d", start, trade_date - timedelta(days=1))
    except Exception as exc:
        run_id = start_job_run(engine, "screen", now)
        finish_job_run(engine, run_id, now, error=str(exc))
        print(f"screen failed: {exc}", file=sys.stderr)
        return 1

    try:
        picks = run_screen(settings, engine, daily_by_symbol, index_daily, universe, trade_date, now,
                           stop_atr_frac=settings.screener.stop_atr_frac,
                           min_room_r=settings.screener.min_room_r,
                           trigger_zone_atr=settings.screener.trigger_zone_atr)
    except Exception as exc:
        # run_screen already recorded the failed job_runs row; don't record a second one.
        print(f"screen failed: {exc}", file=sys.stderr)
        return 1

    for rank, p in enumerate(picks, 1):
        print(f"{rank}. {p.symbol} ({p.direction}) score={p.composite_score:.1f}: {'; '.join(p.reasons)}")

    if settings.telegram.enabled and picks and not args.test:
        rows = [{"rank": i, "symbol": p.symbol, "direction": p.direction,
                "composite_score": p.composite_score, "reasons": "; ".join(p.reasons)}
                for i, p in enumerate(picks, 1)]
        text = shortlist_message(trade_date, rows)
        enqueue_text_alert(engine, "shortlist", f"shortlist:{trade_date}", text, now)
    return 0


def cmd_preopen(settings, args) -> int:
    clock = clock_factory()
    store = store_factory()
    engine = make_engine(settings.paths.db_path)
    now = clock.now()
    trade_date = _resolve_trade_date(args, clock)

    calendar = MarketCalendar(settings.market, load_holidays(settings.paths.static_dir, trade_date.year))
    if not calendar.is_trading_day(trade_date):
        print(f"{trade_date} is not a trading day; skipping preopen")
        return 0

    with engine.connect() as conn:
        rows = conn.execute(
            select(shortlist.c.rank, shortlist.c.symbol, shortlist.c.composite_score, shortlist.c.reasons)
            .where(shortlist.c.trade_date == trade_date.isoformat()).order_by(shortlist.c.rank)
        ).mappings().all()
    if not rows:
        print(f"no shortlist found for {trade_date}; run `tradalgo screen` first")
        return 0
    symbols = [r["symbol"] for r in rows]

    try:
        provider = build_fyers_quote_provider(settings, store, trade_date)
        quotes = provider.get_quotes(symbols)
    except Exception as exc:
        _record_health_event(engine, now, "data",
                             f"FYERS unavailable for pre-open quotes ({exc}); yfinance has no pre-open "
                             "data, skipping preopen annotation")
        return 0

    # Steps before annotate_preopen record their own failure row; annotate_preopen owns the
    # "preopen" job_runs row itself, so its failures must not be recorded a second time here.
    try:
        cache = CandleCache(settings.paths.data_dir / "candles", provider)
        prev_close, daily_atr = {}, {}
        for symbol in symbols:
            df = cache.load(symbol, "1d")
            if df.empty:
                continue
            prev_close[symbol] = float(df["close"].iloc[-1])
            if len(df) >= 14:
                daily_atr[symbol] = float(atr(df).iloc[-1])
    except Exception as exc:
        run_id = start_job_run(engine, "preopen", now)
        finish_job_run(engine, run_id, now, error=str(exc))
        print(f"preopen failed: {exc}", file=sys.stderr)
        return 1

    try:
        results = annotate_preopen(engine, trade_date, quotes, prev_close, daily_atr,
                                   settings.preopen.max_gap_atr, settings.preopen.oppose_gap_atr, now)
    except Exception as exc:
        # annotate_preopen already recorded the failed job_runs row; don't record a second one.
        print(f"preopen failed: {exc}", file=sys.stderr)
        return 1
    by_symbol = {r["symbol"]: r for r in results}

    if settings.telegram.enabled:
        message_rows = [{
            "rank": r["rank"], "symbol": r["symbol"],
            "direction": by_symbol.get(r["symbol"], {}).get("direction") or "",
            "composite_score": r["composite_score"], "reasons": r["reasons"] or "",
            "gap_pct": by_symbol.get(r["symbol"], {}).get("gap_pct"),
            "demoted": by_symbol.get(r["symbol"], {}).get("demoted", False),
        } for r in rows]
        text = shortlist_message(trade_date, message_rows)
        enqueue_text_alert(engine, "shortlist", f"preopen:{trade_date}", text, now)
    return 0


def build_tick_stream_factory(settings, store, today, on_fallback):
    """A TickStream factory bound to today's FYERS token, or None if FYERS auth is unavailable."""
    from tradalgo.data.fyers_auth import get_access_token, require
    from tradalgo.data.fyers_socket import TickStream

    try:
        token = get_access_token(store, today)
        app_id = require(store, "FYERS_APP_ID")
    except Exception as exc:
        on_fallback(f"FYERS unavailable for live ticks ({exc}); running without tick stream")
        return None

    def factory(on_tick):
        return TickStream(token, app_id, on_tick, on_status=lambda msg: print(f"tick stream: {msg}", file=sys.stderr))

    return factory


def cmd_session(settings, args) -> int:
    from tradalgo.engine.live_sink import LiveSink
    from tradalgo.engine.session import LiveSession, run_session, shortlist_symbols

    clock = clock_factory()
    store = store_factory()
    engine = make_engine(settings.paths.db_path)
    now = clock.now()
    trade_date = _resolve_trade_date(args, clock)

    calendar = MarketCalendar(settings.market, load_holidays(settings.paths.static_dir, trade_date.year))
    if not calendar.is_trading_day(trade_date):
        print(f"{trade_date} is not a trading day; skipping session")
        return 0
    if not shortlist_symbols(engine, trade_date):
        print(f"no shortlist for {trade_date}; run `tradalgo screen` first")
        return 0

    def on_fallback(message):
        _record_health_event(engine, now, "data", message)

    provider = build_screen_provider(settings, store, trade_date, on_fallback)
    cache = CandleCache(settings.paths.data_dir / "candles", provider)
    tick_stream_factory = build_tick_stream_factory(settings, store, trade_date, on_fallback)

    def sink_factory(degraded_fn):
        return LiveSink(engine, clock, degraded_fn, settings.telegram.enabled)

    session = LiveSession(settings, engine, clock, provider, cache, sink_factory,
                          tick_stream_factory=tick_stream_factory,
                          state_dir=settings.paths.data_dir / "session")
    started = run_session(settings, engine, clock, session, trade_date)
    if not started:
        print(f"no session today for {trade_date}")
    return 0


def cmd_ci_cycle(settings, args) -> int:
    """One 5-minute cycle and exit — for a scheduler that can't hold a long-lived process (e.g. GitHub
    Actions cron). State is loaded from and saved back to the SQLite DB and the session JSON file, so
    consecutive runs (even in fresh processes/containers) continue the same trading day. No tick stream:
    only the 5-minute bar cycle runs, which is what `LiveSession.run_once` already does on its own."""
    from datetime import time as dt_time

    from tradalgo.engine.live_sink import LiveSink
    from tradalgo.engine.session import LiveSession, poll_telegram_updates, shortlist_symbols, status_text_for
    from tradalgo.jobs.backtest_worker import build_telegram_client, run_worker

    clock = clock_factory()
    store = store_factory()
    engine = make_engine(settings.paths.db_path)
    now = clock.now()
    trade_date = _resolve_trade_date(args, clock)
    data_dir = settings.paths.data_dir

    calendar = MarketCalendar(settings.market, load_holidays(settings.paths.static_dir, trade_date.year))
    if not calendar.is_trading_day(trade_date):
        print(f"{trade_date} is not a trading day; skipping cycle")
        return 0
    if not calendar.is_market_open(now):
        print(f"market is closed at {now.isoformat()}; skipping cycle")
        return 0
    if not shortlist_symbols(engine, trade_date):
        print(f"no shortlist for {trade_date}; run `tradalgo screen` first")
        return 0

    def on_fallback(message):
        _record_health_event(engine, now, "data", message)

    provider = build_screen_provider(settings, store, trade_date, on_fallback)
    cache = CandleCache(data_dir / "candles", provider)

    def sink_factory(degraded_fn):
        return LiveSink(engine, clock, degraded_fn, settings.telegram.enabled)

    session = LiveSession(settings, engine, clock, provider, cache, sink_factory,
                          tick_stream_factory=None, state_dir=data_dir / "session")
    if not session.start(trade_date):
        print(f"no session today for {trade_date}")
        return 0
    if now.time() > dt_time(15, 31):
        session.finish(now)
    else:
        session.run_once(now)

    telegram_client = build_telegram_client(store)
    if telegram_client is None:
        _record_health_event(engine, now, "cycle", "Telegram not configured; alerts stay queued")
    else:
        try:
            run_worker(settings, engine, clock, once=True, telegram_client=telegram_client)
            status_text = status_text_for(engine, clock, data_dir / "session", data_dir)
            poll_telegram_updates(engine, telegram_client, clock, data_dir, store.get("TELEGRAM_CHAT_ID"),
                                  status_text, data_dir / "telegram_offset.json")
        except Exception as exc:
            _record_health_event(engine, now, "cycle", f"telegram send/poll failed: {exc}")

    print(f"cycle complete for {trade_date} at {now.isoformat()}")
    return 0


def cmd_backtest(settings, args) -> int:
    from tradalgo.dashboard.controls import validate_backtest_params
    from tradalgo.data.universe import load_universe
    from tradalgo.jobs.backtest_worker import process_run

    clock = clock_factory()
    engine = make_engine(settings.paths.db_path)
    now = clock.now()

    params = {
        "from": args.from_date, "to": args.to_date, "universe": args.universe,
        "strategies": args.strategies.split(","), "shortlist_size": args.shortlist_size,
        "slippage_pct": args.slippage_pct if args.slippage_pct is not None else settings.backtest.slippage_pct,
        "max_risk_pct": settings.capital.max_risk_pct if args.max_risk_pct is None else args.max_risk_pct,
        "initial_capital": settings.capital.initial_capital if args.capital is None else args.capital,
    }
    try:
        validate_backtest_params(params)
    except ValueError as exc:
        print(f"invalid backtest params: {exc}", file=sys.stderr)
        return 1

    from tradalgo.storage.repo import claim_backtest_run, enqueue_backtest_run

    run_id = enqueue_backtest_run(engine, params, now)
    print(f"queued backtest run {run_id}")

    universe = load_universe(settings.paths.static_dir)

    if claim_backtest_run(engine, run_id, clock.now()):
        print(f"processing backtest run {run_id}...")
        try:
            status = process_run(settings, engine, clock, run_id, universe=universe)
        except KeyboardInterrupt:
            interrupted_at = clock.now()
            with engine.begin() as conn:
                conn.execute(update(backtest_runs).where(backtest_runs.c.id == run_id).values(
                    status="cancelled", error="interrupted by user", finished_at=to_ist(interrupted_at).isoformat()))
            print(f"backtest run {run_id} interrupted by user; marked cancelled", file=sys.stderr)
            return 130
        print(f"run {run_id}: {status}")
    else:
        # A concurrent `tradalgo worker` claimed this run first; wait for it to finish rather than
        # claiming and running someone else's queued backtest instead.
        print(f"run {run_id} is being processed by the worker; waiting...")
        last_progress = None
        try:
            while True:
                with engine.connect() as conn:
                    row = conn.execute(select(backtest_runs.c.status, backtest_runs.c.progress_pct)
                                       .where(backtest_runs.c.id == run_id)).mappings().first()
                if row["progress_pct"] != last_progress:
                    print(f"progress: {row['progress_pct']}%")
                    last_progress = row["progress_pct"]
                if row["status"] in ("done", "failed", "cancelled"):
                    break
                backtest_poll_sleep(backtest_poll_seconds)
        except KeyboardInterrupt:
            print(f"stopped waiting on backtest run {run_id}; it keeps running in the worker", file=sys.stderr)
            return 130

    with engine.connect() as conn:
        row = conn.execute(select(backtest_runs.c.status, backtest_runs.c.metrics_json, backtest_runs.c.error)
                           .where(backtest_runs.c.id == run_id)).mappings().first()

    if row["status"] != "done":
        print(f"backtest {row['status']}: {row['error'] or 'n/a'}", file=sys.stderr)
        return 1

    def _fmt(value):
        return "n/a" if value is None else value

    metrics = json.loads(row["metrics_json"])
    print(f"trades: {metrics['trades']}  win_rate: {metrics['win_rate']:.2%}  "
         f"expectancy_r: {metrics['expectancy_r']:.4f}  expectancy_r_no_slippage: {metrics['expectancy_r_no_slippage']:.4f}")
    print(f"profit_factor: {_fmt(metrics['profit_factor'])}  max_drawdown_r: {metrics['max_drawdown_r']}  "
         f"fill_rate: {_fmt(metrics['fill_rate'])}  missed_entries: {metrics['missed_entries']}")
    print("by_strategy:")
    for name, s in metrics["by_strategy"].items():
        print(f"  {name}: trades={s['trades']} win_rate={s['win_rate']:.2%} expectancy_r={s['expectancy_r']:.4f}")

    gate_pass = metrics["trades"] >= 100 and metrics["expectancy_r"] > 0
    if gate_pass:
        print("M6 gate: PASS")
    else:
        reason = []
        if metrics["trades"] < 100:
            reason.append(f"only {metrics['trades']} trades (need >= 100)")
        if metrics["expectancy_r"] <= 0:
            reason.append(f"expectancy_r {metrics['expectancy_r']} <= 0")
        print(f"M6 gate: FAIL ({'; '.join(reason)})")
    return 0


def cmd_diagnose(settings, args) -> int:
    from tradalgo.backtest.diagnostics import diagnose, load_run, render_markdown

    engine = make_engine(settings.paths.db_path)
    try:
        run = load_run(engine, args.run_id)
    except ValueError as exc:
        print(f"diagnose failed: {exc}", file=sys.stderr)
        return 1
    if run.trades.empty:
        print(f"backtest run {args.run_id} has no trades; nothing to diagnose", file=sys.stderr)
        return 1

    report = diagnose(run)
    markdown = render_markdown(report)
    print(markdown)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"diagnostics-run{args.run_id}.md"
    out_path.write_text(markdown)
    print(f"wrote {out_path}")
    return 0


def cmd_worker(settings, args) -> int:
    import time as time_module

    from tradalgo.jobs.backtest_worker import build_telegram_client, run_worker
    from tradalgo.jobs.maintenance import run_maintenance
    from tradalgo.notify.updates import process_updates  # noqa: F401  (used indirectly by poll_telegram_updates)
    from tradalgo.engine.session import poll_telegram_updates, status_text_for

    clock = clock_factory()
    store = store_factory()
    engine = make_engine(settings.paths.db_path)
    telegram_client = build_telegram_client(store)
    data_dir = settings.paths.data_dir
    offset_path = data_dir / "telegram_offset.json"
    status_text = status_text_for(engine, clock, data_dir / "session", data_dir)
    allowed_chat_id = store.get("TELEGRAM_CHAT_ID")

    def safe_maintenance():
        try:
            run_maintenance(settings, engine, store, clock)
        except Exception as exc:
            _record_health_event(engine, clock.now(), "worker", f"maintenance failed: {exc}")

    def safe_poll():
        if telegram_client is None:
            return
        try:
            poll_telegram_updates(engine, telegram_client, clock, data_dir, allowed_chat_id, status_text, offset_path)
        except Exception as exc:
            _record_health_event(engine, clock.now(), "worker", f"telegram poll failed: {exc}")

    safe_maintenance()
    last_maintenance_date = to_ist(clock.now()).date()
    try:
        while True:
            try:
                run_worker(settings, engine, clock, once=True, telegram_client=telegram_client)
            except Exception as exc:
                _record_health_event(engine, clock.now(), "worker", f"run_worker failed: {exc}")
                time_module.sleep(5)
                continue
            safe_poll()
            today = to_ist(clock.now()).date()
            if today != last_maintenance_date:
                safe_maintenance()
                last_maintenance_date = today
            time_module.sleep(5)
    except KeyboardInterrupt:
        print("worker stopped")
        return 0


def cmd_report(settings, args) -> int:
    from tradalgo import reporting

    clock = clock_factory()
    engine = make_engine(settings.paths.db_path)
    now = clock.now()
    end_date = to_ist(now).date()

    report = reporting.weekly_report(engine, end_date, weeks=args.weeks)
    divergence = reporting.live_vs_backtest(engine, int(args.run_id) if args.run_id else None)
    text = reporting.format_report_text(report, divergence)
    print(text)

    if args.telegram:
        dedup_key = f"report:{report['week_end']}:{args.weeks}"
        enqueue_text_alert(engine, "report", dedup_key, text, now)
    return 0


def cmd_dashboard(settings, args) -> int:
    env = {**os.environ, "TRADALGO_CONFIG": str(Path(args.config).resolve())}
    # launchd runs this job with no venv on PATH, and from an arbitrary cwd
    app = Path(__file__).resolve().parent / "dashboard" / "app.py"
    cmd = [sys.executable, "-m", "streamlit", "run", str(app),
           "--server.address", settings.dashboard.host,
           "--server.port", str(settings.dashboard.port),
           "--server.headless", "true"]
    result = run_subprocess(cmd, env=env)
    return getattr(result, "returncode", 0) or 0


LAUNCHD_DIR = Path(__file__).resolve().parents[1] / "launchd"
LAUNCHD_PLISTS = [
    "com.tradalgo.screen.plist",
    "com.tradalgo.preopen.plist",
    "com.tradalgo.session.plist",
    "com.tradalgo.worker.plist",
    "com.tradalgo.dashboard.plist",
]


def render_launchd_plists(repo_dir: Path, python_path: Path) -> dict[str, str]:
    logdir = repo_dir / "data" / "logs"
    rendered = {}
    for name in LAUNCHD_PLISTS:
        template = (LAUNCHD_DIR / name).read_text()
        rendered[name] = (template
                          .replace("{{REPO}}", str(repo_dir))
                          .replace("{{PYTHON}}", str(python_path))
                          .replace("{{LOGDIR}}", str(logdir)))
    return rendered


def cmd_install_launchd(settings, args) -> int:
    repo_dir = Path(__file__).resolve().parents[1]
    python_path = Path(sys.executable)  # the interpreter actually running this command (usually .venv/bin/python)
    dest = Path(args.dest).expanduser()
    rendered = render_launchd_plists(repo_dir, python_path)

    if args.dry_run:
        for name, content in rendered.items():
            print(f"--- {name} ---")
            print(content)
    else:
        dest.mkdir(parents=True, exist_ok=True)
        for name, content in rendered.items():
            (dest / name).write_text(content)
            print(f"wrote {dest / name}")

    print("\nTo load the agents, run:")
    for name in LAUNCHD_PLISTS:
        print(f"  launchctl bootstrap gui/$(id -u) {dest / name}")
    print("\nA sleeping Mac will not wake for a missed StartCalendarInterval. Schedule a wake with:")
    print("  sudo pmset repeat wakeorpoweron MTWRF 06:55:00")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tradalgo")
    parser.add_argument("--config", default="config.yaml")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="create data directory and SQLite database")
    sub.add_parser("login", help="one-time FYERS browser login (refresh token lasts ~15 days)")
    backfill = sub.add_parser("backfill", help="cache daily + 5m FYERS history for the universe and NIFTY50")
    backfill.add_argument("--months", type=int, default=12)

    screen = sub.add_parser("screen", help="07:00 pre-market screener")
    screen.add_argument("--date", default=None)
    screen.add_argument("--force", action="store_true")
    screen.add_argument("--test", action="store_true",
                        help="if the resolved date isn't a trading day, screen using the last trading "
                             "day's data instead of skipping; never sends a Telegram alert")

    preopen = sub.add_parser("preopen", help="09:08 pre-open gap annotation")
    preopen.add_argument("--date", default=None)

    session = sub.add_parser("session", help="live 5-minute alert session during market hours")
    session.add_argument("--date", default=None)

    ci_cycle = sub.add_parser("ci-cycle", help="one 5-minute cycle then exit (for a cron scheduler, e.g. GitHub Actions)")
    ci_cycle.add_argument("--date", default=None)

    backtest = sub.add_parser("backtest", help="walk-forward strategy backtest")
    backtest.add_argument("--from", dest="from_date", required=True)
    backtest.add_argument("--to", dest="to_date", required=True)
    backtest.add_argument("--universe", default="both", choices=("nifty50", "niftynext50", "both"))
    backtest.add_argument("--strategies", default="orb,gap,vwap,pdhl,pullback,range_breakout")
    backtest.add_argument("--shortlist-size", type=int, default=6)
    backtest.add_argument("--slippage-pct", type=float, default=None)
    backtest.add_argument("--max-risk-pct", type=float, default=None)   # defaults to settings.capital
    backtest.add_argument("--capital", type=float, default=None)

    diagnose = sub.add_parser("diagnose", help="backtest diagnostics report (evidence for tuning)")
    diagnose.add_argument("--run-id", dest="run_id", type=int, required=True)
    diagnose.add_argument("--out", default="data/reports")

    sub.add_parser("worker", help="always-on job worker: backtests, telegram sender/poller, maintenance")

    report = sub.add_parser("report", help="weekly performance and live-vs-backtest report")
    report.add_argument("--weeks", type=int, default=1)
    report.add_argument("--run-id", dest="run_id", default=None)
    report.add_argument("--telegram", action="store_true")

    sub.add_parser("dashboard", help="launch the Streamlit dashboard on 127.0.0.1")

    install_launchd = sub.add_parser("install-launchd", help="render and install launchd plists")
    install_launchd.add_argument("--dest", default="~/Library/LaunchAgents")
    install_launchd.add_argument("--dry-run", action="store_true")

    args = parser.parse_args(argv)

    handlers = {
        "init": cmd_init, "login": cmd_login, "backfill": cmd_backfill,
        "screen": cmd_screen, "preopen": cmd_preopen, "dashboard": cmd_dashboard,
        "install-launchd": cmd_install_launchd, "session": cmd_session, "ci-cycle": cmd_ci_cycle,
        "backtest": cmd_backtest, "worker": cmd_worker, "report": cmd_report, "diagnose": cmd_diagnose,
    }
    return handlers[args.command](load_settings(args.config), args)


if __name__ == "__main__":
    sys.exit(main())
