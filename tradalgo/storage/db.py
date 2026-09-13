from pathlib import Path

from sqlalchemy import Engine, create_engine, event

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


def _add_missing_columns(engine: Engine) -> None:
    """create_all never alters existing tables, so columns added later are ALTERed into older databases."""
    with engine.begin() as conn:
        columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(backtest_trades)")}
        if "legs_json" not in columns:
            conn.exec_driver_sql("ALTER TABLE backtest_trades ADD COLUMN legs_json TEXT")
