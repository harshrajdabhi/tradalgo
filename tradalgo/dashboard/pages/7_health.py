import streamlit as st

from tradalgo.config import KeyringStore
from tradalgo.dashboard import queries
from tradalgo.dashboard.app import get_engine, get_settings
from tradalgo.data.fyers_auth import refresh_token_expiry

st.title("Health")

settings = get_settings()
engine = get_engine(settings)


@st.cache_data(ttl=15)
def _job_runs(_engine):
    return queries.latest_job_runs(_engine)


@st.cache_data(ttl=15)
def _health_events(_engine):
    return queries.health_events(_engine)


@st.cache_data(ttl=15)
def _degraded(_engine, component):
    return queries.degraded_periods(_engine, component)


st.subheader("Latest job runs")
st.dataframe(_job_runs(engine), use_container_width=True)

st.subheader("Data provider health")
st.dataframe(_degraded(engine, "data"), use_container_width=True)

st.subheader("Websocket status")
socket_events = _degraded(engine, "socket")
if socket_events.empty:
    st.info("No websocket health events logged.")
else:
    st.dataframe(socket_events, use_container_width=True)

try:
    expiry = refresh_token_expiry(KeyringStore())
    st.write(f"FYERS refresh token expiry: {expiry.isoformat() if expiry else 'unknown'}")
except Exception:
    st.write("FYERS refresh token expiry: unknown")

st.subheader("Recent health events")
st.dataframe(_health_events(engine), use_container_width=True)
