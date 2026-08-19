"""Weekly page: renders the latest docs/weekly/<date>.md inside the app (read-only, no compute)."""

from __future__ import annotations

import html
import os
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ui  # noqa: E402
from fxradar.config import DISCLAIMER  # noqa: E402
from fxradar.weekly import DEFAULT_REPO_URL, WEEKLY_DIR, read_front_matter  # noqa: E402

ui.sidebar(DISCLAIMER)


def _mtime(p: Path) -> float:
    return os.path.getmtime(p) if p.exists() else -1.0


@st.cache_data(show_spinner=False)
def load_latest(weekly_dir: str, mtime: float) -> tuple[str, dict, str] | None:
    files = sorted(Path(weekly_dir).glob("????-??-??.md"))
    if not files:
        return None
    text = files[-1].read_text()
    fm = read_front_matter(text)
    body = text.split("---", 2)[2] if text.startswith("---") else text
    return files[-1].stem, fm, body


st.markdown(
    '<div class="fx-header"><div><span class="fx-wordmark">Weekly report</span>'
    '<span class="fx-sub">one free page every Monday — regimes, change risk, generic light</span></div></div>',
    unsafe_allow_html=True,
)
ui.mobile_bar()

latest = load_latest(str(WEEKLY_DIR), _mtime(WEEKLY_DIR))
if latest is None:
    ui.card(
        "<p>No weekly report yet — run <code>make weekly</code> "
        "(<code>python -m fxradar.weekly</code>) to write <code>docs/weekly/&lt;monday&gt;.md</code>.</p>",
        title="Nothing published yet",
    )
    ui.footer(DISCLAIMER)
    st.stop()

stem, fm, body = latest
feed_url = f"{DEFAULT_REPO_URL}/blob/main/docs/feed.xml"
page_url = f"{DEFAULT_REPO_URL}/blob/main/docs/weekly/{stem}.md"
ui.card(
    f'<p><b>{html.escape(fm.get("title", stem))}</b><br>'
    f'<span class="fx-muted">{html.escape(fm.get("summary", ""))}</span></p>'
    f'<p class="fx-muted">Published as markdown + e-mail-safe HTML in <code>docs/weekly/</code> · '
    f'<a href="{feed_url}" target="_blank">RSS feed</a> · <a href="{page_url}" target="_blank">this page on GitHub</a> · '
    f"computed numbers only, generic traffic light, never personalised. {html.escape(DISCLAIMER)}</p>",
    title=f"Week of {stem}",
)
st.markdown(body)
ui.footer(DISCLAIMER)
