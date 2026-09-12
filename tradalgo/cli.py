import argparse
import sys
from datetime import timedelta

from tradalgo.clock import SystemClock
from tradalgo.config import KeyringStore, load_settings
from tradalgo.storage.db import init_db, make_engine

PENDING = ["screen", "preopen", "session", "backtest", "worker", "dashboard", "report"]


def cmd_init(settings, args) -> int:
    settings.paths.data_dir.mkdir(parents=True, exist_ok=True)
    init_db(make_engine(settings.paths.db_path))
    print(f"Initialised database at {settings.paths.db_path}")
    return 0


def cmd_login(settings, args) -> int:
    from tradalgo.data.fyers_auth import auth_url, login_with_auth_code, refresh_token_expiry, require

    store = KeyringStore()
    print("Open this URL, log in, then copy the auth_code parameter from the redirect URL:")
    print(auth_url(require(store, "FYERS_APP_ID"), require(store, "FYERS_SECRET_KEY"), settings.fyers.redirect_uri))
    login_with_auth_code(store, input("auth_code: ").strip(), SystemClock().now().date())
    print(f"FYERS tokens stored in keychain; refresh token valid until {refresh_token_expiry(store)}")
    return 0


def cmd_backfill(settings, args) -> int:
    from fyers_apiv3.fyersModel import FyersModel

    from tradalgo.data.base import INDEX_SYMBOL, ProviderError
    from tradalgo.data.candle_cache import CandleCache
    from tradalgo.data.fyers_auth import get_access_token, require
    from tradalgo.data.fyers_provider import FyersProvider
    from tradalgo.data.universe import load_universe, refresh_constituents

    store = KeyringStore()
    today = SystemClock().now().date()
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tradalgo")
    parser.add_argument("--config", default="config.yaml")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="create data directory and SQLite database")
    sub.add_parser("login", help="one-time FYERS browser login (refresh token lasts ~15 days)")
    backfill = sub.add_parser("backfill", help="cache daily + 5m FYERS history for the universe and NIFTY50")
    backfill.add_argument("--months", type=int, default=12)
    for name in PENDING:
        sub.add_parser(name, help="not implemented yet")
    args = parser.parse_args(argv)

    handlers = {"init": cmd_init, "login": cmd_login, "backfill": cmd_backfill}
    if args.command not in handlers:
        print(f"'{args.command}' is not implemented yet", file=sys.stderr)
        return 2
    return handlers[args.command](load_settings(args.config), args)


if __name__ == "__main__":
    sys.exit(main())
