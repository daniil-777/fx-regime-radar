"""FX Regime Radar — app entrypoint (router). Reads small artifacts only (CLAUDE.md rule 8).

Navigation: Overview · Advisor · Strategy lab · Arcade · Methodology. Every page shares the design
system (app/ui.py), the universe switch, and — where it makes sense — the scenario explorer.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ui  # noqa: E402

st.set_page_config(
    page_title="FX Regime Radar", page_icon="📡", layout="wide", initial_sidebar_state="expanded"
)
ui.inject_css()

VIEWS = Path(__file__).resolve().parent / "views"
pages = {
    "Radar": [
        st.Page(str(VIEWS / "overview.py"), title="Overview", default=True),
        st.Page(str(VIEWS / "advisor.py"), title="Advisor"),
    ],
    "Research": [
        st.Page(str(VIEWS / "strategy_lab.py"), title="Strategy lab"),
        st.Page(str(VIEWS / "arcade.py"), title="Arcade"),
    ],
    "About": [st.Page(str(VIEWS / "methodology.py"), title="Methodology")],
}
nav = st.navigation(pages, position="sidebar")
nav.run()
