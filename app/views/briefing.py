"""Briefing — the AI presenter, hosted. Reads/embeds only (CLAUDE.md rule 8): the widget is served
by the Rust service (`/avatar`); this page embeds it over HTTPS with microphone permission and
explains exactly what the presenter is and is not. The proof page stays human-free by design."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ui  # noqa: E402
from fxradar.config import DISCLAIMER  # noqa: E402

ui.sidebar(DISCLAIMER)


@st.cache_data(ttl=30, show_spinner=False)
def _local_presenter() -> str:
    """Dev convenience: if no FXRADAR_AVATAR_URL is set, look for a presenter on localhost:8080
    (`make avatar` starts one). A 0.3 s probe, cached 30 s — the page still only embeds."""
    import urllib.request

    try:
        with urllib.request.urlopen("http://localhost:8080/avatar/greeting", timeout=0.3) as r:
            if r.status == 200:
                return "http://localhost:8080/avatar"
    except Exception:  # noqa: BLE001 — any failure just means "not running"
        pass
    return ""


AVATAR_URL = os.environ.get("FXRADAR_AVATAR_URL", "") or _local_presenter()

st.markdown(
    '<div class="fx-header"><div><span class="fx-wordmark">Briefing</span>'
    '<span class="fx-sub">ask the radar — an AI presenter grounded in today’s published numbers</span></div></div>',
    unsafe_allow_html=True,
)

ui.card(
    '<div style="font-size:0.9rem;line-height:1.6">A computer-generated presenter that answers '
    "questions about the radar — the current regimes, the change risk and its band, the siren, the "
    "consensus, the live record — <b>only</b> from the numbers the pipeline published today and a "
    "fixed methodology FAQ. Every generated sentence passes two gates before it is spoken: the "
    "direction-word lint and a numeric-grounding check (a number not in today’s pack cannot be "
    "said). It never discusses price direction, never gives advice, and introduces itself as an AI "
    "in its first sentence.</div>"
    '<div class="fx-dim" style="font-size:0.78rem;margin-top:8px">Conversations are logged and '
    "reviewed weekly by a human; transcripts are used for nothing else. The Proof page stays "
    "presenter-free on purpose — the ledger speaks for itself.</div>",
    title="What this is — and what it will never say",
)

if AVATAR_URL:
    # a hand-rolled iframe: st.components.v1.iframe cannot grant microphone permission,
    # which silently killed voice conversation inside this page
    st.markdown(
        f'<iframe src="{AVATAR_URL}" style="width:100%;height:780px;border:0;border-radius:12px" '
        'allow="microphone; autoplay" title="AI presenter"></iframe>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="fx-dim" style="font-size:0.74rem">Served from <span class="fx-num">{AVATAR_URL}</span> '
        "over WebRTC; the microphone streams only while the mic button in the widget is on.</div>",
        unsafe_allow_html=True,
    )
else:
    ui.state(
        "The presenter is not connected in this deployment.",
        "The widget is served by the Rust service and is off by default (feature flag).",
        "Locally: run `make avatar` in a second terminal and reload this page — it finds the "
        "presenter on localhost automatically. Deployed: set FXRADAR_AVATAR=on on the service and "
        "FXRADAR_AVATAR_URL (e.g. https://<host>/avatar) here. Setup: docs/AVATAR.md.",
    )

ui.footer(
    DISCLAIMER, "· The presenter speaks published numbers only; the record lives on the Proof page."
)
