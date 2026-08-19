"""FX Regime Radar — app entrypoint (router). Reads small artifacts only (CLAUDE.md rule 8).

Navigation: Overview · Advisor · Regime space · Strategy lab · Arcade · Methodology. Every page shares the design
system (app/ui.py), the universe switch, and — where it makes sense — the scenario explorer.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
# Hosted deploys sometimes skip `pip install -e .`; the package lives in src/ next to app/.
sys.path.insert(1, str(Path(__file__).resolve().parents[1] / "src"))
import ui  # noqa: E402

st.set_page_config(
    page_title="FX Regime Radar", page_icon="📡", layout="wide", initial_sidebar_state="auto"
)
ui.inject_css()

VIEWS = Path(__file__).resolve().parent / "views"
pages = {
    "Radar": [
        st.Page(str(VIEWS / "overview.py"), title="Overview", default=True),
        st.Page(str(VIEWS / "advisor.py"), title="Advisor"),
        st.Page(str(VIEWS / "treasury.py"), title="Treasury"),
        st.Page(str(VIEWS / "regime_space.py"), title="Regime space"),
        st.Page(str(VIEWS / "probability_space.py"), title="Probability space"),
    ],
    "Research": [
        st.Page(str(VIEWS / "strategy_lab.py"), title="Strategy lab"),
        st.Page(str(VIEWS / "arcade.py"), title="Arcade"),
    ],
    "Trust": [st.Page(str(VIEWS / "proof.py"), title="Proof")],
    "About": [
        st.Page(str(VIEWS / "methodology.py"), title="Methodology"),
        st.Page(str(VIEWS / "weekly.py"), title="Weekly report"),
        st.Page(str(VIEWS / "metrics.py"), title="Metrics"),
    ],
}
nav = st.navigation(pages, position="sidebar")
nav.run()
