import argparse
import sys

from tradalgo.config import load_settings
from tradalgo.storage.db import init_db, make_engine

PENDING = ["login", "backfill", "screen", "preopen", "session", "backtest", "worker", "dashboard", "report"]


def cmd_init(args) -> int:
    settings = load_settings(args.config)
    settings.paths.data_dir.mkdir(parents=True, exist_ok=True)
    init_db(make_engine(settings.paths.db_path))
    print(f"Initialised database at {settings.paths.db_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tradalgo")
    parser.add_argument("--config", default="config.yaml")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="create data directory and SQLite database")
    for name in PENDING:
        sub.add_parser(name, help="not implemented yet")
    args = parser.parse_args(argv)

    if args.command == "init":
        return cmd_init(args)
    print(f"'{args.command}' is not implemented yet", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
