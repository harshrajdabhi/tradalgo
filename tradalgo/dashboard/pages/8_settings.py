import os

import streamlit as st
import yaml

from tradalgo.dashboard import controls
from tradalgo.dashboard.app import get_settings

st.title("Settings")

config_path = os.environ.get("TRADALGO_CONFIG", "config.yaml")

try:
    settings = get_settings()
    with open(config_path) as f:
        current = yaml.safe_load(f)
except Exception as exc:
    st.error(f"Could not load config: {exc}")
    current = None

if current is not None:
    st.subheader("Current config")
    st.json(current)

    st.subheader("Edit")
    with st.form("settings_form"):
        initial_capital = st.number_input(
            "Initial capital", min_value=0.0, value=float(current["capital"]["initial_capital"]))
        max_risk_pct = st.number_input(
            "Max risk %", min_value=0.0001, max_value=0.03, value=float(current["capital"]["max_risk_pct"]))
        shortlist_size = st.slider(
            "Shortlist size", min_value=5, max_value=7, value=int(current["screener"]["shortlist_size"]))
        strategy_toggles = {}
        for name, cfg in current["strategies"].items():
            strategy_toggles[name] = st.checkbox(f"{name} enabled", value=bool(cfg["enabled"]))
        partial_exit_at_r = st.number_input(
            "Partial exit at R", min_value=0.0,
            value=float(current["position_management"]["partial_exit_at_r"]))
        save = st.form_submit_button("Save")

    if save:
        new_config = dict(current)
        new_config["capital"] = dict(current["capital"], initial_capital=initial_capital,
                                     max_risk_pct=max_risk_pct)
        new_config["screener"] = dict(current["screener"], shortlist_size=shortlist_size)
        new_config["strategies"] = {
            name: dict(cfg, enabled=strategy_toggles[name]) for name, cfg in current["strategies"].items()
        }
        new_config["position_management"] = dict(
            current["position_management"], partial_exit_at_r=partial_exit_at_r)
        try:
            controls.save_settings(config_path, new_config)
            st.success("Settings saved; a backup of the previous config was created.")
            st.rerun()
        except Exception as exc:
            st.error(f"Invalid settings, not saved: {exc}")
