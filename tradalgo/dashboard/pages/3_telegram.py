import streamlit as st

from tradalgo.dashboard import controls, queries
from tradalgo.dashboard.app import get_engine, get_settings

st.title("Telegram")

settings = get_settings()
engine = get_engine(settings)

status_filter = st.selectbox("Status", options=[None, "queued", "sent", "failed", "edited", "expired"],
                             format_func=lambda s: s or "all")
date_filter = st.date_input("Date", value=None)


@st.cache_data(ttl=15)
def _alerts(_engine, status, date_str):
    return queries.alerts_log(_engine, status=status, trade_date=date_str)


df = _alerts(engine, status_filter, date_filter.isoformat() if date_filter else None)

sent_today = int((df["status"] == "sent").sum()) if not df.empty else 0
failed = int((df["status"] == "failed").sum()) if not df.empty else 0
awaiting = int(df["user_action"].isna().sum()) if not df.empty and "user_action" in df.columns else 0

col1, col2, col3 = st.columns(3)
col1.metric("Sent", sent_today)
col2.metric("Failed", failed)
col3.metric("Awaiting reply", awaiting)

st.dataframe(df, use_container_width=True)

failed_rows = df[df["status"] == "failed"] if not df.empty else df
for row in failed_rows.itertuples():
    if st.button(f"Resend alert {row.alert_id}", key=f"resend_{row.alert_id}"):
        controls.resend_alert(engine, row.alert_id)
        st.cache_data.clear()
        st.rerun()
