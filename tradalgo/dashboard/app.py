import os
from datetime import datetime

import streamlit as st

from tradalgo.clock import IST, MarketCalendar, load_holidays
from tradalgo.config import KeyringStore, Settings, load_settings
from tradalgo.data.fyers_auth import refresh_token_expiry
from tradalgo.dashboard import controls
from tradalgo.storage.db import init_db, make_engine

PAGES = [
    "pages/1_today.py",
    "pages/2_positions.py",
    "pages/3_telegram.py",
    "pages/4_backtest.py",
    "pages/5_journal.py",
    "pages/6_analytics.py",
    "pages/7_health.py",
    "pages/8_settings.py",
]


def get_settings() -> Settings:
    return load_settings(os.environ.get("TRADALGO_CONFIG", "config.yaml"))


def get_engine(settings: Settings | None = None):
    settings = settings or get_settings()
    engine = make_engine(settings.paths.db_path)
    init_db(engine)
    return engine


def render_sidebar(settings: Settings) -> None:
    now = datetime.now(IST)
    try:
        holidays = load_holidays(settings.paths.static_dir, now.year)
        calendar = MarketCalendar(settings.market, holidays)
        status = "OPEN" if calendar.is_market_open(now) else "CLOSED"
    except Exception:
        status = "unknown"
    st.sidebar.metric("Market", status)

    kill_on = controls.kill_switch_active(settings.paths.data_dir)
    new_kill_on = st.sidebar.toggle("Kill switch", value=kill_on)
    if new_kill_on != kill_on:
        controls.set_kill_switch(settings.paths.data_dir, new_kill_on)
        st.rerun()

    try:
        expiry = refresh_token_expiry(KeyringStore())
        expiry_str = expiry.isoformat() if expiry else "unknown"
    except Exception:
        expiry_str = "unknown"
    st.sidebar.write(f"FYERS token expiry: {expiry_str}")
    st.sidebar.write(f"DB: {settings.paths.db_path}")


def main() -> None:
    st.set_page_config(page_title="TradAlgo", layout="wide")
    settings = get_settings()
    render_sidebar(settings)
    nav = st.navigation([st.Page(p) for p in PAGES])
    nav.run()


if __name__ == "__main__":
    main()
