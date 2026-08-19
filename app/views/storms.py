"""Storms: three named crises replayed day by day through the real scoring path — causal reconstruction,
clearly separated from the live record. Reads data/storm_replays.json + reports/storms/*.md only."""

from __future__ import annotations

import html
import json
import os
import re
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ui  # noqa: E402
from fxradar import config  # noqa: E402
from fxradar.config import DISCLAIMER  # noqa: E402

ui.sidebar(DISCLAIMER)

REPLAYS_PATH = config.DATA_DIR / "storm_replays.json"
STORMS_DIR = config.REPORTS_DIR / "storms"
PRICES_PATH = config.PRICES_PATH
REGIME_ORDER = ["calm", "trend", "chop", "crisis"]


def _mtime(p: Path) -> float:
    return os.path.getmtime(p) if p.exists() else -1.0


@st.cache_data(show_spinner=False)
def load_replays(path: str, mtime: float) -> dict:
    return json.loads(Path(path).read_text())


@st.cache_data(show_spinner=False)
def load_closes(path: str, mtime: float, pair: str, start: str, end: str) -> pd.DataFrame:
    """Close prices of one pair inside the window (the only slice of prices.parquet the page needs)."""
    px = pd.read_parquet(path, columns=["date", "pair", "close"])
    px = px[(px["pair"] == pair) & (px["date"] >= start) & (px["date"] <= end)]
    return px.sort_values("date").reset_index(drop=True)


@st.cache_data(show_spinner=False)
def load_report(path: str, mtime: float) -> str:
    return Path(path).read_text() if Path(path).exists() else ""


st.markdown(
    '<div class="fx-header"><div><span class="fx-wordmark">Storms</span>'
    '<span class="fx-sub">three named crises, replayed exactly as the radar would have seen them</span></div></div>',
    unsafe_allow_html=True,
)
ui.mobile_bar()

if not REPLAYS_PATH.exists():
    ui.card(
        "<p>No <code>storm_replays.json</code> yet — run <code>make storms</code> "
        "(or <code>python -m fxradar.replay</code>) to replay the three windows.</p>",
        title="Nothing to show yet",
    )
    ui.footer(DISCLAIMER)
    st.stop()

replays = load_replays(str(REPLAYS_PATH), _mtime(REPLAYS_PATH))
keys = list(replays)
labels = {k: f"{replays[k]['title']} · {replays[k]['pair']}" for k in keys}
key = st.radio(
    "storm", keys, format_func=lambda k: labels[k], horizontal=True, label_visibility="collapsed"
)
entry = replays[key]
pair = entry["pair"]
thr = float(entry.get("threshold", 0.22))
rows = pd.DataFrame(entry["rows"])
if rows.empty:
    ui.card(
        "<p>This window holds no rows — rerun <code>make storms</code>.</p>", title="Empty window"
    )
    ui.footer(DISCLAIMER)
    st.stop()
rows["date"] = pd.to_datetime(rows["date"])
told = rows[rows["pair"] == pair].sort_values("date").reset_index(drop=True)
story = entry.get("storyline") or {}

# ---- banner: causal reconstruction, not the live record -------------------------------------
st.markdown(
    f'<div class="fx-card" style="border-color:{ui.REGIME_COLORS["chop"]}66;padding:12px 16px;margin-bottom:12px">'
    f'<span style="color:{ui.REGIME_COLORS["chop"]};font-weight:500">{html.escape(entry.get("causal_note", ""))}</span>'
    f'<div class="fx-muted" style="font-size:0.85rem;margin-top:4px">{html.escape(entry.get("selection_rule", ""))} '
    f"Every row below was computed from prices truncated at that day and the saved models "
    f"(model {html.escape(str(entry.get('model_version', '')))}); nothing was refit.</div></div>",
    unsafe_allow_html=True,
)
proof_page = Path(__file__).resolve().parent / "proof.py"
if proof_page.exists():
    try:  # only resolvable inside the st.navigation router (app.py); plain text otherwise
        st.page_link(str(proof_page), label="→ Proof page: the live, hash-chained record")
    except Exception:
        st.caption("The live, hash-chained record is on the Proof page (side panel).")

# ---- KPI strip: the numbers ---------------------------------------------------------------
if story:
    lag = story.get("alarm_to_flip_days")
    ui.kpi_strip(
        [
            ui.kpi(
                "first alarm",
                story.get("first_alarm") or "none",
                f"change risk ≥ {thr:.2f}",
                ui.REGIME_COLORS["chop"] if story.get("first_alarm") else ui.MUTED,
            ),
            ui.kpi(
                "first crisis day",
                story.get("first_crisis") or "none",
                f"{story.get('n_crisis_days', 0)} crisis days of {story.get('n_days', 0)}",
                ui.REGIME_COLORS["crisis"] if story.get("first_crisis") else ui.MUTED,
            ),
            ui.kpi(
                "alarm → flip",
                "–" if lag is None else f"{lag:+d} d",
                "trading days (negative: the flip came first)",
                ui.TEXT,
            ),
            ui.kpi(
                "peak siren",
                f"{story.get('peak_siren_pct', 0):.0f}",
                f"on {story.get('peak_siren')} · {story.get('n_loud_days', 0)} days ≥ 98",
                ui.REGIME_COLORS["crisis"],
            ),
        ]
    )

# ---- reconstruction figure: close + regime bands, change risk, siren -------------------------
px = load_closes(str(PRICES_PATH), _mtime(PRICES_PATH), pair, entry["start"], entry["end"])
legend = " ".join(ui.regime_pill(r) for r in REGIME_ORDER)
st.markdown(
    f'<div style="display:flex;justify-content:space-between;align-items:center;margin:6px 0 -4px 2px">'
    f'<span style="font-weight:500">{html.escape(pair)} — {html.escape(entry["title"])}: close with replayed regime bands, change risk, siren</span><span>{legend}</span></div>',
    unsafe_allow_html=True,
)
fig = make_subplots(
    rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.04, row_heights=[0.5, 0.25, 0.25]
)
if len(px):
    fig.add_trace(
        go.Scatter(
            x=px["date"],
            y=px["close"],
            mode="lines",
            name="close",
            line=dict(color=ui.TEXT, width=1.3),
            hovertemplate="%{x|%Y-%m-%d}<br>close %{y}<extra></extra>",
        ),
        row=1,
        col=1,
    )
fig.add_trace(
    go.Scatter(
        x=told["date"],
        y=100 * told["change_risk_5d"].astype(float),
        mode="lines",
        name="change risk %",
        line=dict(color=ui.REGIME_COLORS["trend"], width=1.4),
        hovertemplate="%{x|%Y-%m-%d}<br>change risk %{y:.0f} %<extra></extra>",
    ),
    row=2,
    col=1,
)
if "risk_hi" in told.columns and told["risk_hi"].notna().any():
    fig.add_trace(
        go.Scatter(
            x=pd.concat([told["date"], told["date"][::-1]]),
            y=pd.concat(
                [100 * told["risk_hi"].astype(float), (100 * told["risk_lo"].astype(float))[::-1]]
            ),
            fill="toself",
            fillcolor=ui.REGIME_COLORS["trend"],
            opacity=0.15,
            line=dict(width=0),
            name="90 % conformal band",
            hoverinfo="skip",
        ),
        row=2,
        col=1,
    )
fig.add_trace(
    go.Scatter(
        x=told["date"],
        y=told["anomaly_pct"].astype(float),
        mode="lines+markers",
        name="siren pct",
        line=dict(color=ui.REGIME_COLORS["crisis"], width=1.1),
        marker=dict(size=5),
        hovertemplate="%{x|%Y-%m-%d}<br>siren pct %{y:.0f}<extra></extra>",
    ),
    row=3,
    col=1,
)
shapes = ui.regime_bands(ui.runs_from_labels(told["date"], told["regime"]))
if entry.get("event_date"):
    shapes.append(
        dict(
            type="line",
            xref="x",
            yref="paper",
            x0=entry["event_date"],
            x1=entry["event_date"],
            y0=0,
            y1=1,
            line=dict(color=ui.MUTED, width=1, dash="dot"),
        )
    )
fig.add_hline(y=100 * thr, line=dict(color=ui.MUTED, width=1, dash="dash"), row=2, col=1)
fig.add_hline(y=98, line=dict(color=ui.MUTED, width=1, dash="dash"), row=3, col=1)
fig.update_layout(
    template=ui.PLOTLY_TEMPLATE,
    height=560,
    shapes=shapes,
    showlegend=False,
    margin=dict(l=40, r=20, t=20, b=40),
    hovermode="x unified",
)
fig.update_yaxes(title_text="close", row=1, col=1)
fig.update_yaxes(title_text="change risk %", range=[0, 100], row=2, col=1)
fig.update_yaxes(title_text="siren pct", range=[0, 103], row=3, col=1)
st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
st.caption(
    f"Bands: the replayed filtered regime of each day. Dashed: alarm threshold {thr:.2f} and siren 98. "
    f"Dotted: {html.escape(str(entry.get('event_label', 'reference event')))}."
)

# ---- narrative (from the markdown report) + day-by-day table ------------------------------------
report_path = STORMS_DIR / f"{key}_{pair}.md"
report = load_report(str(report_path), _mtime(report_path))
left, right = st.columns([1.05, 1])
with left:
    if report:
        # the report's own numbers/table/png are rendered above; show the prose sections + sidebar
        body = re.split(r"^## Day by day\s*$", report, maxsplit=1, flags=re.M)
        prose = body[0].split("## Buildup", 1)
        prose = "## Buildup" + prose[1] if len(prose) > 1 else body[0]
        tail = body[1] if len(body) > 1 else ""
        extra = re.split(r"^## (?=The other pairs|Sidebar)", tail, maxsplit=1, flags=re.M)
        extra_md = ("## " + extra[1]) if len(extra) > 1 else ""
        st.markdown(
            '<div class="fx-section" style="margin-top:4px">What the radar showed, day by day '
            '<span class="fx-dim" style="font-weight:400;font-size:0.78rem">· templated from the replayed numbers — no hindsight, no direction words</span></div>',
            unsafe_allow_html=True,
        )
        # the report's markdown prose: ## headings become quiet section labels, not page titles
        prose = re.sub(r"^## (.+)$", r"**\1**", prose, flags=re.M)
        st.markdown(prose)
        if extra_md:
            st.markdown(re.sub(r"^## (.+)$", r"**\1**", extra_md, flags=re.M))
    else:
        ui.card(
            f"<p>No report at <code>{html.escape(str(report_path.relative_to(config.ROOT)))}</code> — "
            "run <code>make storms</code>.</p>",
            title="Report missing",
        )
with right:
    table = pd.DataFrame(
        {
            "date": told["date"].dt.strftime("%Y-%m-%d"),
            "regime": told["regime"],
            "conf": told["regime_prob"].astype(float),
            "risk %": 100 * told["change_risk_5d"].astype(float),
            "siren": told["anomaly_pct"].astype(float),
        }
    )
    if "risk_hi" in told.columns and told["risk_hi"].notna().any():
        table["band %"] = [
            f"{100 * lo:.0f}–{100 * hi:.0f}" if pd.notna(hi) else "–"
            for lo, hi in zip(told["risk_lo"], told["risk_hi"], strict=True)
        ]
    if "consensus_text" in told.columns and told["consensus_text"].notna().any():
        table["votes"] = told["consensus_text"].fillna("–").astype(str).str.slice(0, 9)
    tbl = ui.html_table(table, {"conf": "{:.2f}", "risk %": "{:.0f}", "siren": "{:.0f}"})
    for rname in REGIME_ORDER:
        tbl = tbl.replace(f"<td>{rname}</td>", f"<td>{ui.regime_pill(rname)}</td>")
    ui.card(
        "<div class='fx-muted' style='font-size:0.8rem;margin-bottom:8px'>one row per trading day; "
        "every value was computable on that day</div>" + tbl,
        title=f"{html.escape(pair)} — day by day",
    )

ui.card(
    f"<p><b>Selection rule.</b> {html.escape(entry.get('selection_rule', ''))}</p>"
    "<p><b>Method.</b> For each trading day t the price history is cut at t and pushed through the saved "
    "models exactly as the daily pipeline does: causal features → filtered HMM → forecaster → siren "
    "(→ conformal band and consensus where those modules exist). Only day t is kept. A test asserts that "
    "every replayed row equals the full-history artifact and the live ledger to 1e-9 — if it did not, "
    "something in the pipeline would be looking ahead.</p>"
    f"<p class='fx-muted' style='font-size:0.85rem'>{html.escape(entry.get('causal_note', ''))} "
    "Full reports: <code>reports/storms/</code> · method: <code>docs/STORMS.md</code>.</p>",
    title="How to read this page",
)
ui.footer(DISCLAIMER)
