"""Metrics page: the five public numbers (ledger days, subscribers, keys, partners, MRR) — honest zeros."""

from __future__ import annotations

import html
import json
import os
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ui  # noqa: E402
from fxradar.config import DISCLAIMER  # noqa: E402
from fxradar.metrics_page import HEADLINE, METRICS_PATH  # noqa: E402
from fxradar.weekly import DEFAULT_REPO_URL, WEEKLY_DIR  # noqa: E402

ui.sidebar(DISCLAIMER)


def _mtime(p: Path) -> float:
    return os.path.getmtime(p) if p.exists() else -1.0


@st.cache_data(show_spinner=False)
def load_metrics(path: str, mtime: float) -> dict:
    return json.loads(Path(path).read_text())


@st.cache_data(show_spinner=False)
def latest_report(weekly_dir: str, mtime: float) -> str | None:
    files = sorted(Path(weekly_dir).glob("????-??-??.md"))
    return files[-1].stem if files else None


st.markdown(
    '<div class="fx-header"><div><span class="fx-wordmark">Metrics</span>'
    '<span class="fx-sub">the five numbers, read from artifacts — zeros are real zeros</span></div></div>',
    unsafe_allow_html=True,
)
ui.mobile_bar()

if not METRICS_PATH.exists():
    ui.card(
        "<p>No <code>data/metrics.json</code> yet — run <code>make metrics</code> "
        "(<code>python -m fxradar.metrics_page</code>).</p>",
        title="Metrics not built",
    )
    ui.footer(DISCLAIMER)
    st.stop()

m = load_metrics(str(METRICS_PATH), _mtime(METRICS_PATH))
tiles = []
for key, label in HEADLINE:
    value = m.get(key, 0)
    shown = f"{float(value):,.0f}" if key == "mrr_chf" else str(value)
    color = ui.TEXT if value else ui.MUTED
    sub = {
        "ledger_days_live": "hash-chained forward test",
        "report_subscribers": "opt-in list: none stored",
        "active_api_keys": "keys with revoked = 0",
        "design_partners": "status = signed in tracking.csv",
        "mrr_chf": "sum of signed monthly_chf",
    }[key]
    tiles.append(ui.kpi(label, shown, sub, color))
ui.kpi_strip(tiles)

latest = latest_report(str(WEEKLY_DIR), _mtime(WEEKLY_DIR))
weekly_url = f"{DEFAULT_REPO_URL}/blob/main/docs/weekly"
feed_url = f"{DEFAULT_REPO_URL}/blob/main/docs/feed.xml"
latest_line = (
    f'<a href="{weekly_url}/{html.escape(latest)}.md" target="_blank">week of {html.escape(latest)}</a>'
    if latest
    else "none yet — run <code>make weekly</code>"
)
ui.card(
    f"<p><b>Zeros are real zeros.</b> Every number above is read from an artifact "
    f"(<code>live_record.json</code>, <code>keys.db</code>, <code>docs/outreach/tracking.csv</code>), "
    f"never estimated, and nothing is stored about readers (see <code>docs/PRIVACY.md</code>).</p>"
    f'<p class="fx-muted">Forecasts recorded / resolved: <span class="fx-num">{int(m.get("forecasts_recorded", 0))} / '
    f'{int(m.get("forecasts_resolved", 0))}</span> · weekly reports published: '
    f'<span class="fx-num">{int(m.get("weekly_reports_published", 0))}</span> · '
    f'generated <span class="fx-num">{html.escape(str(m.get("generated_at", "—")))}</span></p>'
    f'<p>Latest weekly report: {latest_line} · <a href="{feed_url}" target="_blank">RSS feed</a> · '
    f"ledger: <code>data/ledger.parquet</code> (<code>python -m fxradar.ledger --verify</code>), "
    f'<a href="{DEFAULT_REPO_URL}/blob/main/data/live_record.json" target="_blank">live_record.json</a></p>',
    title="What these numbers are",
)
ui.footer(DISCLAIMER)
