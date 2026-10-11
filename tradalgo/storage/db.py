from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.exc import OperationalError

from tradalgo.storage.schema import metadata


def make_engine(db_path: str | Path) -> Engine:
    engine = create_engine(f"sqlite:///{db_path}")

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()

    return engine


def init_db(engine: Engine) -> None:
    metadata.create_all(engine)
    _add_missing_columns(engine)


# (table, column, SQL type) added after the first release; create_all never alters existing tables
MIGRATIONS = [("backtest_trades", "legs_json", "TEXT")]


def _columns(conn, table: str) -> set[str]:
    return {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}


def _add_missing_columns(engine: Engine) -> None:
    """Idempotent under concurrent init_db calls (worker, session, API on one old DB)."""
    for table, column, sql_type in MIGRATIONS:
        with engine.begin() as conn:
            if column in _columns(conn, table):
                continue
        try:
            with engine.begin() as conn:
                conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}")
        except OperationalError as exc:
            if "duplicate column name" not in str(exc):
                raise
