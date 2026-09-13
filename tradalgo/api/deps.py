"""Per-request settings/engine, resolved from TRADALGO_CONFIG (default config.yaml).

No FYERS client construction and no engine run happens here or anywhere in tradalgo/api: this
process only reads the DB the always-on worker writes, plus the read-only candle cache.
"""
import os
from functools import lru_cache

from sqlalchemy import Engine

from tradalgo.config import Settings, load_settings
from tradalgo.storage.db import init_db, make_engine


def config_path() -> str:
    return os.environ.get("TRADALGO_CONFIG", "config.yaml")


@lru_cache(maxsize=8)
def _cached_engine(db_path: str) -> Engine:
    engine = make_engine(db_path)
    init_db(engine)
    return engine


def get_settings(path: str | None = None) -> Settings:
    return load_settings(path or config_path())


def settings_for_request(request) -> Settings:
    """Resolve Settings from the app's own config path (set at create_app time), not a
    process-global env var, so multiple apps/TestClients can coexist in one process.
    """
    return load_settings(getattr(request.app.state, "config_path", None) or config_path())


def get_engine(settings: Settings | None = None) -> Engine:
    settings = settings or get_settings()
    return _cached_engine(str(settings.paths.db_path))
