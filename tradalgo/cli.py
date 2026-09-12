import argparse
import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import insert, select

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
from tradalgo.storage.schema import health_events, shortlist

PENDING = ["session", "backtest", "worker", "report"]

# Injection points for tests: monkeypatch these instead of hitting the network or keychain.
clock_factory = SystemClock
store_factory = KeyringStore
run_subprocess = subprocess.run


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
        print(f"{trade_date} is not a trading day; skipping screen")
        return 0
    if not args.force and has_job_succeeded_on(engine, "screen", trade_date):
        print(f"screen already succeeded for {trade_date}; use --force to rerun")
        return 0

    for problem in refresh_constituents(settings.paths.static_dir):
        print(f"warning: {problem}", file=sys.stderr)
    universe = load_universe(settings.paths.static_dir)

    def on_fallback(message):
        _record_health_event(engine, now, "data", message)

    try:
        provider = build_screen_provider(settings, store, trade_date, on_fallback)
        cache = CandleCache(settings.paths.data_dir / "candles", provider)
        start = trade_date - timedelta(days=400)
        symbols = [c.symbol for c in universe]
        daily_by_symbol = {s: cache.get(s, "1d", start, trade_date - timedelta(days=1)) for s in symbols}
        index_daily = cache.get(INDEX_SYMBOL, "1d", start, trade_date - timedelta(days=1))
        picks = run_screen(settings, engine, daily_by_symbol, index_daily, universe, trade_date, now,
                           stop_atr_frac=settings.screener.stop_atr_frac,
                           min_room_r=settings.screener.min_room_r,
                           trigger_zone_atr=settings.screener.trigger_zone_atr)
    except Exception as exc:
        run_id = start_job_run(engine, "screen", now)
        finish_job_run(engine, run_id, now, error=str(exc))
        print(f"screen failed: {exc}", file=sys.stderr)
        return 1

    for rank, p in enumerate(picks, 1):
        print(f"{rank}. {p.symbol} ({p.direction}) score={p.composite_score:.1f}: {'; '.join(p.reasons)}")

    if settings.telegram.enabled and picks:
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

    cache = CandleCache(settings.paths.data_dir / "candles", provider)
    prev_close, daily_atr = {}, {}
    for symbol in symbols:
        df = cache.load(symbol, "1d")
        if df.empty:
            continue
        prev_close[symbol] = float(df["close"].iloc[-1])
        if len(df) >= 14:
            daily_atr[symbol] = float(atr(df).iloc[-1])

    results = annotate_preopen(engine, trade_date, quotes, prev_close, daily_atr,
                               settings.preopen.max_gap_atr, settings.preopen.oppose_gap_atr, now)
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


def cmd_dashboard(settings, args) -> int:
    env = {**os.environ, "TRADALGO_CONFIG": str(Path(args.config).resolve())}
    cmd = ["streamlit", "run", "tradalgo/dashboard/app.py",
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
    python_path = repo_dir / ".venv" / "bin" / "python"
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

    preopen = sub.add_parser("preopen", help="09:08 pre-open gap annotation")
    preopen.add_argument("--date", default=None)

    sub.add_parser("dashboard", help="launch the Streamlit dashboard on 127.0.0.1")

    install_launchd = sub.add_parser("install-launchd", help="render and install launchd plists")
    install_launchd.add_argument("--dest", default="~/Library/LaunchAgents")
    install_launchd.add_argument("--dry-run", action="store_true")

    for name in PENDING:
        sub.add_parser(name, help="not implemented yet")
    args = parser.parse_args(argv)

    handlers = {
        "init": cmd_init, "login": cmd_login, "backfill": cmd_backfill,
        "screen": cmd_screen, "preopen": cmd_preopen, "dashboard": cmd_dashboard,
        "install-launchd": cmd_install_launchd,
    }
    if args.command not in handlers:
        print(f"'{args.command}' is not implemented yet", file=sys.stderr)
        return 2
    return handlers[args.command](load_settings(args.config), args)


if __name__ == "__main__":
    sys.exit(main())
