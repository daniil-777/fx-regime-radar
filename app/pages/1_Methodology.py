"""Methodology page: explains the models, splits, and honesty metrics in plain language (phase 05)."""

import streamlit as st

from fxradar.config import DISCLAIMER

st.set_page_config(page_title="Methodology — FX Regime Radar", page_icon="📡", layout="wide")

with st.sidebar:
    st.markdown("**FX Regime Radar**")
    st.caption(DISCLAIMER)

st.title("Methodology")
st.caption("Coming in phase 05.")
st.markdown("---")
st.caption(DISCLAIMER)
