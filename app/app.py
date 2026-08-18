"""FX Regime Radar — Streamlit app shell.

Placeholder for phase 00. The real dashboard arrives in phase 05. The app only ever
READS small artifacts written by pipelines/run_daily.py (CLAUDE.md rule 8).
"""

import streamlit as st

from fxradar.config import DISCLAIMER

st.set_page_config(page_title="FX Regime Radar", page_icon="📡", layout="wide")

st.title("FX Regime Radar")
st.caption("A weather station for currency markets — regimes, change risk, anomalies.")
st.info("Scaffold only (v0.1.0). Data, models, and the dashboard arrive in later phases.")

with st.sidebar:
    st.markdown("**FX Regime Radar**")
    st.caption(DISCLAIMER)

st.markdown("---")
st.caption(DISCLAIMER)
