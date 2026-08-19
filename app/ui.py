"""Shared UI for the Streamlit app: CSS (fonts, cards, pills), the single Plotly template, and
small HTML helpers. Everything visual lives here so pages stay thin (CLAUDE.md design system).

Phase 31 (trust-first UI): every colour comes from design/tokens.json via `fxradar.tokens` — no hex
literal may appear in app/ or src/ (`make lint-ui`). Two signature structures live here: the
condition banner (`condition_banner`) and the trust strip (`trust_strip`). Motion budget: the orb
is the one ambient element; the only other motion is the live dot's slow pulse.
"""

from __future__ import annotations

import html
import json
import os
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

from fxradar import tokens as tk

# ---- design tokens (single source: design/tokens.json) ------------------------------------
BG = tk.BG  # nimbus — app background
SURFACE = tk.SURFACE  # front — cards, sidebar
LINE = tk.LINE  # rgba hairline for CSS borders
BORDER = tk.BORDER  # hex twin of the hairline for SVG/Plotly strokes
GRID = tk.GRID
TEXT = tk.TEXT
MUTED = tk.MUTED
DIM = tk.DIM
ACCENT = tk.ACCENT  # beacon: links and actions only
REGIME_COLORS = tk.REGIME_COLORS
REGIME_BLURB = {
    "calm": "low volatility, quiet drift",
    "trend": "moderate volatility, persistent direction",
    "chop": "moderate volatility, no direction",
    "crisis": "high volatility, storm conditions",
}
FONT_UI = tk.FONT_UI
FONT_MONO = tk.FONT_MONO
FONT_DISPLAY = tk.FONT_DISPLAY
alpha = tk.with_alpha

CSS = f"""
<style>
@import url('{tk.FONT_IMPORT}');
{tk.css_variables()}
#MainMenu, footer, [data-testid="stToolbarActions"], [data-testid="stAppDeployButton"], [data-testid="stMainMenu"], [data-testid="stMainMenuButton"], [data-testid="stDecoration"], [data-testid="stStatusWidget"], .stDeployButton {{ display: none !important; visibility: hidden !important; }}
header[data-testid="stHeader"] {{ background: transparent !important; pointer-events: none; }}
header[data-testid="stHeader"] button {{ pointer-events: auto; background: {SURFACE}; border: 1px solid {LINE}; border-radius: 8px; color: {TEXT}; }}
[data-testid="stSidebarCollapseButton"] button, [data-testid="stSidebarCollapsedControl"] button {{ color: {MUTED}; }}
html, body, [data-testid="stAppViewContainer"], .stApp {{ background: {BG} !important; color: {TEXT}; font-family: {FONT_UI}; font-size: 15px; line-height: 1.55; }}
[data-testid="stSidebar"] {{ background: {SURFACE} !important; border-right: 1px solid {LINE}; }}
[data-testid="stSidebar"] *:not([data-testid="stIconMaterial"]):not(.material-symbols-rounded) {{ font-family: {FONT_UI}; }}
.block-container {{ padding-top: 1.4rem; padding-bottom: 2rem; max-width: 1280px; }}
h1, h2, h3, h4 {{ font-family: {FONT_UI}; color: {TEXT}; letter-spacing: -0.005em; font-weight: 500; }}
p, li, label, .stMarkdown {{ color: {TEXT}; }}
a, a:visited {{ color: {ACCENT}; text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
:focus-visible, button:focus-visible, a:focus-visible, [role="tab"]:focus-visible {{ outline: 2px solid {ACCENT} !important; outline-offset: 2px; }}
strong, b {{ font-weight: 500; }}
.fx-num {{ font-family: {FONT_MONO}; font-variant-numeric: tabular-nums; font-feature-settings: 'tnum'; }}
.fx-muted {{ color: {MUTED}; }}
.fx-dim {{ color: {DIM}; }}
.fx-disp {{ font-family: {FONT_DISPLAY}; font-weight: 500; letter-spacing: 0.01em; }}
.fx-card {{ background: {SURFACE}; border: 1px solid {LINE}; border-radius: 12px; padding: 18px 20px; margin-bottom: 14px; }}
.fx-card h3 {{ margin: 0 0 8px 0; font-size: 0.78rem; font-weight: 400; color: {DIM}; letter-spacing: 0.04em; text-transform: uppercase; }}
.fx-header {{ display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 10px; border-bottom: 1px solid {LINE}; padding-bottom: 10px; gap: 12px; flex-wrap: wrap; }}
.fx-wordmark {{ font-family: {FONT_DISPLAY}; font-size: 1.25rem; font-weight: 500; letter-spacing: 0.04em; }}
.fx-sub {{ color: {DIM}; margin-left: 12px; font-size: 0.85rem; }}
.fx-right {{ color: {MUTED}; font-size: 0.8rem; text-align: right; font-family: {FONT_MONO}; }}
.fx-live {{ display: inline-flex; align-items: center; gap: 7px; font-family: {FONT_MONO}; font-size: 0.76rem; color: {MUTED}; }}
.fx-dot {{ width: 7px; height: 7px; border-radius: 50%; background: {REGIME_COLORS["calm"]}; display: inline-block; animation: fx-lp 2.4s ease-in-out infinite; }}
@keyframes fx-lp {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0.35; }} }}
@media (prefers-reduced-motion: reduce) {{ .fx-dot, .fx-now {{ animation: none; }} }}
.fx-now {{ animation: fx-lp 2.4s ease-in-out infinite; }}  /* the trace's end point — the same single heartbeat as the live dot */
.fx-pill {{ display: inline-flex; align-items: center; gap: 6px; padding: 3px 10px; border-radius: 999px; font-weight: 500; font-size: 0.78rem; letter-spacing: 0.02em; font-family: {FONT_UI}; }}
.fx-pill::before {{ content: ""; width: 7px; height: 7px; border-radius: 50%; background: currentColor; display: inline-block; }}
.fx-pill-lg {{ padding: 6px 14px; font-size: 1rem; font-family: {FONT_DISPLAY}; }}
.fx-bar {{ height: 6px; border-radius: 3px; background: {LINE}; overflow: hidden; margin: 8px 0 4px 0; }}
.fx-bar > div {{ height: 100%; border-radius: 3px; }}
.fx-kv {{ display: flex; justify-content: space-between; font-size: 0.84rem; color: {MUTED}; }}
.fx-table {{ width: 100%; border-collapse: collapse; font-size: 0.85rem; }}
.fx-table th {{ text-align: left; color: {DIM}; font-weight: 400; padding: 8px 10px; border-bottom: 1px solid {LINE}; font-size: 0.76rem; letter-spacing: 0.03em; text-transform: uppercase; }}
.fx-table td {{ padding: 8px 10px; border-bottom: 1px solid {LINE}; font-family: {FONT_MONO}; font-variant-numeric: tabular-nums; font-feature-settings: 'tnum'; text-align: right; }}
.fx-table th:not(:first-child) {{ text-align: right; }}
.fx-table td:first-child {{ font-family: {FONT_UI}; text-align: left; }}
.fx-footer {{ color: {DIM}; font-size: 0.78rem; margin-top: 28px; padding-top: 12px; border-top: 1px solid {LINE}; }}
div[data-testid="stSelectbox"] label, div[data-testid="stDateInput"] label, div[data-testid="stTextInput"] label, div[data-testid="stNumberInput"] label, div[data-testid="stSlider"] label, div[data-testid="stRadio"] label {{ color: {MUTED}; font-size: 0.78rem; }}
.fx-side-h {{ color: {DIM}; font-size: 0.7rem; letter-spacing: 0.08em; text-transform: uppercase; margin: 14px 0 -6px 0; }}
.fx-kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; margin: 4px 0 14px 0; }}
.fx-kpi {{ background: {SURFACE}; border: 1px solid {LINE}; border-radius: 12px; padding: 12px 14px; }}
.fx-kpi-l {{ color: {DIM}; font-size: 0.72rem; letter-spacing: 0.04em; text-transform: uppercase; }}
.fx-kpi-v {{ font-size: 1.3rem; font-weight: 500; margin-top: 2px; }}
.fx-kpi-s {{ color: {MUTED}; font-size: 0.76rem; margin-top: 2px; font-family: {FONT_MONO}; }}
.fx-section {{ font-weight: 500; font-size: 0.98rem; margin: 18px 0 8px 2px; }}
.fx-alert {{ display: flex; gap: 10px; align-items: center; padding: 8px 10px; border-radius: 8px; border: 1px solid {LINE}; margin-bottom: 6px; font-size: 0.84rem; }}
[data-testid="stSidebarNav"] a span:not([data-testid="stIconMaterial"]) {{ color: {TEXT}; font-family: {FONT_UI}; }}
[data-testid="stSidebarNav"] a {{ border-radius: 8px; }}
[data-testid="stSidebarNav"] a[aria-current="page"] {{ border-left: 2px solid {REGIME_COLORS["calm"]}; border-radius: 0 8px 8px 0; }}
[data-testid="stSidebarNavSeparator"] {{ border-color: {LINE}; }}
div[data-testid="stExpander"] details {{ background: {SURFACE}; border: 1px solid {LINE}; border-radius: 12px; }}
button[kind="secondary"], .stButton > button {{ border-radius: 999px; border: 1px solid {LINE}; background: {SURFACE}; color: {TEXT}; font-weight: 500; }}
.stButton > button:hover {{ border-color: {ACCENT}; color: {ACCENT}; }}
.fx-table-wrap {{ overflow-x: auto; -webkit-overflow-scrolling: touch; }}
.fx-mobile-bar {{ display: flex; flex-wrap: wrap; gap: 8px 14px; align-items: center; margin: -4px 0 10px 0; }}
.fx-mobile-hint {{ color: {MUTED}; font-size: 0.74rem; }}
/* ---- signature 1: the condition banner ----------------------------------------------- */
.fx-banner {{ padding: 22px 0 14px 0; }}
.fx-eyebrow {{ font-family: {FONT_MONO}; font-size: 0.76rem; color: {DIM}; letter-spacing: 0.08em; text-transform: uppercase; }}
.fx-condrow {{ display: flex; align-items: flex-end; justify-content: space-between; gap: 24px; flex-wrap: wrap; }}
.fx-cond {{ font-family: {FONT_DISPLAY}; font-weight: 500; font-size: clamp(52px, 8vw, 84px); line-height: 1.05; letter-spacing: -0.01em; }}
.fx-metrics {{ font-family: {FONT_MONO}; font-size: 0.9rem; color: {MUTED}; font-feature-settings: 'tnum'; margin-top: 4px; }}
.fx-metrics .fx-dim {{ color: {DIM}; }}
.fx-consensus {{ font-size: 0.78rem; color: {DIM}; text-align: right; padding-bottom: 8px; }}
.fx-votes {{ display: flex; gap: 14px; margin-top: 6px; justify-content: flex-end; }}
.fx-votes span {{ display: inline-flex; align-items: center; gap: 5px; color: {MUTED}; font-size: 0.78rem; }}
.fx-pip {{ width: 8px; height: 8px; border-radius: 50%; display: inline-block; border: 1.5px solid {DIM}; }}
.fx-trace {{ margin-top: 12px; display: block; }}
.fx-trace-axis {{ display: flex; justify-content: space-between; font-family: {FONT_MONO}; font-size: 0.68rem; color: {DIM}; margin-top: 2px; letter-spacing: 0.02em; }}
.fx-clamp {{ display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }}
.fx-clamp2 {{ display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }}
/* ---- inputs: defined fields, not blended blobs --------------------------------------- */
[data-baseweb="select"] > div, [data-testid="stNumberInput"] div[data-baseweb="input"], [data-testid="stDateInput"] div[data-baseweb="input"], [data-testid="stTextInput"] div[data-baseweb="input"] {{ background: {BG} !important; border: 1px solid {LINE} !important; border-radius: 8px !important; }}
[data-baseweb="select"] > div:focus-within, div[data-baseweb="input"]:focus-within {{ border-color: {ACCENT} !important; }}
[data-testid="stNumberInput"] button {{ background: {SURFACE}; border-left: 1px solid {LINE}; }}
[data-testid="stSidebarNavSectionHeader"], [data-testid="stSidebarNav"] header {{ font-family: {FONT_MONO} !important; font-size: 0.68rem !important; letter-spacing: 0.1em; text-transform: uppercase; color: {DIM} !important; font-weight: 400 !important; }}
[data-testid="stSidebarNav"] a span {{ font-size: 0.9rem; }}
[data-testid="stSidebarNav"] a:hover {{ background: {BG}; }}
.fx-table tbody tr:hover td {{ background: {BG}; }}
[data-testid="stSegmentedControl"] button {{ border-radius: 999px !important; font-family: {FONT_UI}; font-size: 0.82rem; }}
[data-testid="stSegmentedControl"] button[aria-checked="true"], [data-testid="stSegmentedControl"] button[data-active="true"] {{ border-color: {ACCENT} !important; color: {TEXT} !important; }}
/* ---- signature 2: the trust strip ---------------------------------------------------- */
.fx-trust {{ border-top: 1px solid {LINE}; border-bottom: 1px solid {LINE}; padding: 9px 0; margin: 6px 0 14px 0; display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap; font-family: {FONT_MONO}; font-size: 0.76rem; color: {MUTED}; font-feature-settings: 'tnum'; }}
.fx-trust .fx-dim {{ color: {DIM}; }}
.fx-trust a {{ color: {ACCENT}; }}
.fx-state {{ border: 1px dashed {LINE}; border-radius: 12px; padding: 16px 18px; color: {MUTED}; font-size: 0.88rem; }}
.fx-state b {{ color: {TEXT}; }}
/* ---- responsive: one layout that adapts (no device sniffing) --------------------------- */
@media (min-width: 769px) {{ .fx-mobile-hint {{ display: none; }} .fx-mobile-bar {{ margin: 2px 0 4px 0; }} }}
@media (max-width: 768px) {{
  .block-container {{ padding: 3.4rem 0.85rem 2rem 0.85rem !important; }}  /* room for the » sidebar button */
  .fx-header {{ flex-direction: column; align-items: flex-start; gap: 2px; margin-bottom: 10px; }}
  .fx-wordmark {{ font-size: 1.1rem; }}
  .fx-sub {{ display: block; margin-left: 0; font-size: 0.82rem; }}
  .fx-right {{ text-align: left; font-size: 0.74rem; }}
  .fx-kpis {{ grid-template-columns: 1fr 1fr; gap: 8px; }}
  .fx-kpi {{ padding: 10px 12px; }}
  .fx-kpi-v {{ font-size: 1.1rem; }}
  .fx-card {{ padding: 14px; margin-bottom: 10px; }}
  .fx-pill-lg {{ padding: 5px 12px; font-size: 0.95rem; }}
  .fx-table {{ font-size: 0.8rem; }}
  .fx-table th, .fx-table td {{ padding: 6px 8px; white-space: nowrap; }}
  .fx-section {{ margin-top: 12px; }}
  .fx-banner {{ padding: 12px 0 8px 0; }}
  .fx-cond {{ font-size: clamp(44px, 14vw, 64px); }}
  .fx-consensus {{ text-align: left; }}
  .fx-votes {{ justify-content: flex-start; }}
  .fx-trust {{ font-size: 0.7rem; gap: 6px; }}
  [data-testid="stSidebar"] {{ width: min(86vw, 330px) !important; }}
  .stButton > button, [data-testid="stSegmentedControl"] button {{ min-height: 40px; }}  /* touch targets */
  .st-key-fx_mobile_bar [data-testid="stSegmentedControl"] button {{ min-height: 40px; }}
}}
@media (max-width: 1024px) {{
  [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"]:nth-child(3)) > [data-testid="stColumn"] {{ min-width: calc(50% - 8px); }}
  .fx-kpis {{ grid-template-columns: 1fr 1fr; }}
}}
@media (max-width: 640px) {{
  .st-key-fx_orb {{ display: none; }}   /* the 3-D orb is decorative; phones get the numbers only */
}}
@media (max-width: 400px) {{
  .fx-kpis {{ grid-template-columns: 1fr; }}
  .fx-cond {{ font-size: 40px; }}
}}
</style>
"""


def inject_css() -> None:
    """Inject the design system once per page run."""
    st.markdown(CSS, unsafe_allow_html=True)


# ---- Plotly template (defined once, reused everywhere) ---------------------------------
def _register_template() -> None:
    if "fxradar_dark" in pio.templates:
        return
    tpl = go.layout.Template()
    tpl.layout = go.Layout(
        paper_bgcolor="rgba(0,0,0,0)",  # transparent: the card or page paints the ground
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONT_UI, color=TEXT, size=12),
        xaxis=dict(gridcolor=GRID, zeroline=False, linecolor=GRID, tickfont=dict(family=FONT_MONO)),
        yaxis=dict(gridcolor=GRID, zeroline=False, linecolor=GRID, tickfont=dict(family=FONT_MONO)),
        margin=dict(l=40, r=20, t=40, b=40),
        legend=dict(bgcolor="rgba(0,0,0,0)", orientation="h", y=1.05, x=0),
        hoverlabel=dict(
            bgcolor=SURFACE, bordercolor=BORDER, font=dict(family=FONT_MONO, color=TEXT)
        ),
        colorway=[
            TEXT,
            REGIME_COLORS["trend"],
            REGIME_COLORS["calm"],
            REGIME_COLORS["chop"],
            REGIME_COLORS["crisis"],
        ],
    )
    pio.templates["fxradar_dark"] = tpl


_register_template()
PLOTLY_TEMPLATE = "fxradar_dark"


def runs_from_labels(dates: pd.Series, labels: pd.Series) -> pd.DataFrame:
    """Consecutive same-label days merged into runs: regime, start, end (end = next run's start)."""
    g = pd.DataFrame({"date": pd.to_datetime(dates).to_numpy(), "regime": labels.to_numpy()})
    g = g.sort_values("date").reset_index(drop=True)
    if g.empty:
        return pd.DataFrame(columns=["regime", "start", "end"])
    new_run = g["regime"].ne(g["regime"].shift(1)).cumsum()
    runs = g.groupby(new_run).agg(
        regime=("regime", "first"), start=("date", "first"), end=("date", "last")
    )
    runs["end"] = runs["start"].shift(-1).fillna(runs["end"])
    return runs.reset_index(drop=True)


def regime_bands(
    runs: pd.DataFrame,
    opacity: float = 0.10,
    ribbon: bool = True,
    ribbon_height: float = 0.022,
) -> list[dict]:
    """Plotly shapes for regime runs (columns regime, start, end) — the ONE way bands are drawn.

    Two layers, the way macro terminals shade context: a faint full-height tint (10 %, so the
    price line stays the loudest thing on the chart) and a thin, fully saturated ribbon along the
    baseline that carries the categorical state on its own. Regime is never colour-only on the
    page (the legend pills name them), and the ribbon is readable even when the tint is not."""
    shapes = []
    for r in runs.itertuples(index=False):
        color = REGIME_COLORS.get(str(r.regime), MUTED)
        shapes.append(
            dict(
                type="rect",
                xref="x",
                yref="paper",
                x0=r.start,
                x1=r.end,
                y0=0,
                y1=1,
                fillcolor=color,
                opacity=opacity,
                line_width=0,
                layer="below",
            )
        )
        if ribbon:
            shapes.append(
                dict(
                    type="rect",
                    xref="x",
                    yref="paper",
                    x0=r.start,
                    x1=r.end,
                    y0=0,
                    y1=ribbon_height,
                    fillcolor=color,
                    opacity=0.95,
                    line_width=0,
                    layer="above",
                )
            )
    return shapes


# ---- HTML helpers ----------------------------------------------------------------------
def regime_pill(name: str, large: bool = False) -> str:
    """Coloured pill for a regime name."""
    color = REGIME_COLORS.get(name, MUTED)
    cls = "fx-pill fx-pill-lg" if large else "fx-pill"
    return f'<span class="{cls}" style="background:{alpha(color, 0.12)};color:{color};border:1px solid {alpha(color, 0.35)}">{html.escape(name)}</span>'


def confidence_bar(p: float, color: str = TEXT, label: str = "confidence") -> str:
    """Horizontal bar for a probability in [0, 1] with a mono-font readout."""
    pct = max(0.0, min(1.0, float(p))) * 100
    return (
        f'<div class="fx-kv"><span>{html.escape(label)}</span><span class="fx-num">{pct:.0f}%</span></div>'
        f'<div class="fx-bar"><div style="width:{pct:.1f}%;background:{color}"></div></div>'
    )


def risk_color(p: float) -> str:
    """Band colour for a change-risk probability: <20 % muted, 20–40 % amber, >40 % crisis red."""
    pct = float(p) * 100
    return MUTED if pct < 20 else (REGIME_COLORS["chop"] if pct <= 40 else REGIME_COLORS["crisis"])


def risk_gauge(
    p: float,
    drivers: list[str] | None = None,
    lo: float | None = None,
    hi: float | None = None,
    regime: str | None = None,
) -> str:
    """Horizontal change-risk gauge with band colour, the conformal band [lo, hi] as a translucent
    segment behind the bar (phase 22), and the top drivers beneath."""
    pct = max(0.0, min(1.0, float(p))) * 100
    color = risk_color(p)
    ticks = "".join(
        f'<div style="position:absolute;left:{t}%;top:-2px;width:1px;height:12px;background:{BORDER}"></div>'
        for t in (20, 40)
    )
    band, band_txt = "", ""
    if lo is not None and hi is not None and lo == lo and hi == hi:  # NaN-safe
        lo_p, hi_p = max(0.0, float(lo)) * 100, min(1.0, float(hi)) * 100
        band = f'<div style="position:absolute;left:{lo_p:.1f}%;width:{max(0.0, hi_p - lo_p):.1f}%;top:0;height:100%;background:{alpha(color, 0.2)};border-radius:4px"></div>'
        wide = " · bands are wide on purpose" if regime == "crisis" else ""
        band_txt = f'<div class="fx-dim" style="font-size:0.72rem;margin-top:2px">90 % band <span class="fx-num">{lo_p:.0f}–{hi_p:.0f}%</span>{wide}</div>'
    drv = ""
    if drivers:
        drv = f'<div class="fx-muted" style="font-size:0.75rem;margin-top:4px">drivers: {html.escape(", ".join(str(d) for d in drivers))}</div>'
    return (
        f'<div class="fx-kv" style="margin-top:10px"><span>5-day change risk</span><span class="fx-num" style="color:{color}">{pct:.0f}%</span></div>'
        f'<div class="fx-bar" style="position:relative;overflow:visible">{band}<div style="position:relative;width:{pct:.1f}%;background:{color};height:100%;border-radius:4px"></div>{ticks}</div>'
        f"{band_txt}{drv}"
    )


def consensus_meter(
    agreement: int | None, votes: dict | None = None, text: str | None = None
) -> str:
    """Three-dot consensus module (phase 21): one dot per voter (HMM · BOCPD · vol rule), filled
    when that voter sees stress, with the agreement count and the template sentence."""
    if agreement is None or agreement != agreement:
        return ""
    votes = votes or {}
    names = [("hmm", "vote_hmm"), ("bocpd", "vote_bocpd"), ("vol", "vote_vol")]
    level = int(agreement)
    color = (
        REGIME_COLORS["crisis"] if level == 3 else REGIME_COLORS["chop"] if level == 2 else MUTED
    )
    dots = "".join(
        f'<span title="{label}" style="display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:5px;'
        f'background:{color if int(votes.get(key, 0) or 0) else "transparent"};border:1.5px solid {color if int(votes.get(key, 0) or 0) else BORDER}"></span>'
        for label, key in names
    )
    sentence = (
        f'<span class="fx-muted" style="font-size:0.76rem">{html.escape(str(text))}</span>'
        if text
        else ""
    )
    return (
        f'<div style="display:flex;align-items:center;gap:10px;margin-top:8px;flex-wrap:wrap">'
        f'<span style="display:inline-flex;align-items:center">{dots}</span>'
        f'<span class="fx-num" style="font-size:0.8rem;color:{color}">{level}/3</span>{sentence}</div>'
    )


def stale_badge(status: dict | None) -> str:
    """Header pill from data/status.json: models fresh / watch / stale (phase 20 drift monitor)."""
    if not status:
        return ""
    stale = bool(status.get("model_stale"))
    watch = any(v.get("status") == "watch" for v in status.get("features", {}).values())
    color = (
        REGIME_COLORS["crisis"]
        if stale
        else (REGIME_COLORS["chop"] if watch else REGIME_COLORS["calm"])
    )
    word = "models stale" if stale else ("drift watch" if watch else "models fresh")
    return (
        f'<span class="fx-pill" title="PSI / KS / HMM log-likelihood vs the train era — see Proof" '
        f'style="font-size:0.65rem;padding:2px 8px;color:{color};background:{alpha(color, 0.12)};border:1px solid {alpha(color, 0.35)}">{word}</span>'
    )


def siren_color(pct: float) -> str:
    """Anomaly percentile band: muted <90, amber 90–98, crisis red >98."""
    return MUTED if pct < 90 else (REGIME_COLORS["chop"] if pct <= 98 else REGIME_COLORS["crisis"])


def siren_dial(pct: float, label: str) -> str:
    """Compact dial: a ring whose filled arc is the anomaly percentile, coloured by band."""
    pct = max(0.0, min(100.0, float(pct)))
    color = siren_color(pct)
    r, c = 26, 2 * 3.14159 * 26
    dash = c * pct / 100
    return (
        f'<div style="display:flex;align-items:center;gap:14px">'
        f'<svg width="64" height="64" viewBox="0 0 64 64"><circle cx="32" cy="32" r="{r}" fill="none" stroke="{BORDER}" stroke-width="6"/>'
        f'<circle cx="32" cy="32" r="{r}" fill="none" stroke="{color}" stroke-width="6" stroke-linecap="round" stroke-dasharray="{dash:.1f} {c:.1f}" transform="rotate(-90 32 32)"/>'
        f'<text x="32" y="37" text-anchor="middle" font-family="IBM Plex Mono, monospace" font-size="14" fill="{TEXT}">{pct:.0f}</text></svg>'
        f'<div><div style="font-weight:500">{html.escape(label)}</div><div class="fx-muted" style="font-size:0.8rem">anomaly percentile</div></div></div>'
    )


def narration(entry: dict | None, compact: bool = False) -> str:
    """Quote-style narration paragraph with a tiny source badge (AI / auto) and its timestamp.
    `compact` clamps the text to three lines (full text in the tooltip) — progressive disclosure
    for the market cards; the Pairs page shows it in full."""
    if not entry or not entry.get("text"):
        return ""
    ai = entry.get("source") == "llm"
    badge_color = REGIME_COLORS["trend"] if ai else MUTED
    badge = f'<span class="fx-pill" style="font-size:0.65rem;padding:2px 8px;color:{badge_color};background:{alpha(badge_color, 0.12)};border:1px solid {alpha(badge_color, 0.35)}">{"AI" if ai else "auto"}</span>'
    stamp = str(entry.get("generated_at", ""))
    when = html.escape(
        stamp[:16].replace("T", " ") if "T" in stamp else stamp
    )  # ISO timestamps trimmed to minutes
    clamp = ' class="fx-clamp"' if compact else ""
    return (
        f'<div style="margin-top:12px;padding:10px 12px;border-left:3px solid {BORDER};color:{TEXT};font-size:0.86rem;line-height:1.45">'
        f'<div{clamp} title="{html.escape(entry["text"])}">{html.escape(entry["text"])}</div>'
        f'<div class="fx-muted" style="font-size:0.72rem;margin-top:6px">{badge} &nbsp;{when} UTC'
        + (' · <span class="fx-dim">full text on the Pairs page</span>' if compact else "")
        + "</div></div>"
    )


def card(body_html: str, title: str | None = None) -> None:
    """Render a card (surface, 1px border, 12px radius, 20px padding)."""
    head = f"<h3>{html.escape(title)}</h3>" if title else ""
    st.markdown(f'<div class="fx-card">{head}{body_html}</div>', unsafe_allow_html=True)


def sparkline_svg(values: pd.Series, color: str, width: int = 220, height: int = 44) -> str:
    """Inline SVG sparkline (no Plotly overhead for tiny charts)."""
    v = pd.Series(values, dtype=float).dropna().to_numpy()
    if len(v) < 2:
        return ""
    lo, hi = float(v.min()), float(v.max())
    span = hi - lo if hi > lo else 1.0
    xs = [i * (width - 2) / (len(v) - 1) + 1 for i in range(len(v))]
    ys = [height - 2 - (val - lo) / span * (height - 4) for val in v]
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys, strict=True))
    return (
        f'<svg width="100%" height="{height}" viewBox="0 0 {width} {height}" preserveAspectRatio="none" style="display:block;margin-top:10px;max-width:{width}px">'
        f'<polyline fill="none" stroke="{color}" stroke-width="1.6" stroke-linejoin="round" vector-effect="non-scaling-stroke" points="{pts}"/>'
        f'<circle cx="{xs[-1]:.1f}" cy="{ys[-1]:.1f}" r="2.4" fill="{color}"/></svg>'
    )


def html_table(df: pd.DataFrame, formats: dict[str, str] | None = None) -> str:
    """Styled HTML table; `formats` maps column -> format spec (e.g. '{:.1f}')."""
    formats = formats or {}
    head = "".join(f"<th>{html.escape(str(c))}</th>" for c in df.columns)
    rows = []
    for _, r in df.iterrows():
        cells = []
        for c in df.columns:
            val = r[c]
            if c in formats and pd.notna(val) and not isinstance(val, str):
                try:
                    cells.append(f"<td>{formats[c].format(val)}</td>")
                except (ValueError, TypeError):
                    cells.append(f"<td>{html.escape(str(val))}</td>")
            elif (isinstance(val, float) and pd.isna(val)) or val is None:
                cells.append('<td class="fx-muted">–</td>')
            else:
                cells.append(f"<td>{html.escape(str(val))}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return f'<div class="fx-table-wrap"><table class="fx-table"><thead><tr>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'


def sidebar(disclaimer: str) -> None:
    """Sidebar chrome: wordmark + disclaimer (page-specific widgets are added by the page)."""
    with st.sidebar:
        st.markdown(
            '<div class="fx-wordmark" style="font-size:1.1rem">FX Regime Radar</div>',
            unsafe_allow_html=True,
        )
        st.caption(disclaimer)


REPO_URL = os.environ.get("FXRADAR_REPO_URL", "https://github.com/daniil-777/fx-regime-radar")


def footer(disclaimer: str, extra: str = "") -> None:
    """Every surface ends with the rule-7 line, the legal drafts (phase 28) and no direction talk."""
    legal = (
        f' · <a href="{REPO_URL}/blob/main/docs/TERMS.md">terms</a>'
        f' · <a href="{REPO_URL}/blob/main/docs/PRIVACY.md">privacy</a>'
        f' · <a href="{REPO_URL}/blob/main/docs/PRICING.md">pricing</a>'
    )
    st.markdown(
        f'<div class="fx-footer">{html.escape(disclaimer)} {extra}{legal}</div>',
        unsafe_allow_html=True,
    )


def available_universes() -> list[str]:
    """Universes whose artifacts exist on disk (fx first)."""
    from fxradar import config, universes

    out = [
        n
        for n in universes.UNIVERSES
        if (config.universe_dirs(n)["data"] / "regimes.parquet").exists()
    ]
    return out or ["fx"]


def universe_selector() -> tuple[str, object, dict]:
    """Sidebar universe switch shared by every page: returns (name, Universe, dirs). Persisted in
    session state so pages agree; the FX universe keeps the repository default paths."""
    from fxradar import config, universes

    names = available_universes()
    # deep-link support: ?universe=crypto seeds the selection once (shareable scenario links)
    qp = st.query_params.get("universe") if hasattr(st, "query_params") else None
    if qp in names and not st.session_state.get("_universe_from_url"):
        st.session_state["universe_select"] = qp
        st.session_state["_universe_from_url"] = True
    current = st.session_state.get("universe", names[0])
    if current not in names:
        current = names[0]
    # widget value lives in session state (seeded here, no `index=`): the sidebar selectbox and the
    # mobile bar's segmented control are two views of the same choice, kept equal by callbacks
    st.session_state.setdefault("universe_select", current)
    if st.session_state["universe_select"] not in names:
        st.session_state["universe_select"] = names[0]
    st.session_state["_universe_names"] = names
    with st.sidebar:
        label = st.selectbox(
            "Universe",
            names,
            format_func=lambda n: universes.get(n).label,
            key="universe_select",
            on_change=_sync_state("universe_select", "m_universe"),
        )
    st.session_state["universe"] = label
    return label, universes.get(label), config.universe_dirs(label)


def _sync_state(src: str, dst: str):
    """Callback factory: copy widget `src` into widget `dst` (both keyed in session state).
    A deselected segmented control yields None — then restore `src` from `dst` instead."""

    def _cb() -> None:
        value = st.session_state.get(src)
        if value is None:
            st.session_state[src] = st.session_state.get(dst)
        else:
            st.session_state[dst] = value

    return _cb


def mobile_bar(uni=None, pairs: list[str] | None = None) -> None:
    """Compact controls for small screens (hidden on desktop by CSS, where the sidebar shows).
    Universe + market as segmented controls; episode / as-of date stay in the side panel."""
    from fxradar import universes

    names = st.session_state.get("_universe_names") or []
    with st.container(key="fx_mobile_bar"):
        cols = st.columns([1, 1]) if (len(names) > 1 and pairs) else [st.container(), None]
        if len(names) > 1:
            st.session_state.setdefault(
                "m_universe", st.session_state.get("universe_select", names[0])
            )
            with cols[0]:
                st.segmented_control(
                    "Universe",
                    names,
                    format_func=lambda n: universes.get(n).label,
                    key="m_universe",
                    on_change=_sync_state("m_universe", "universe_select"),
                    label_visibility="collapsed",
                )
        if pairs and uni is not None:
            side_key, m_key = f"pair_{uni.name}", f"m_pair_{uni.name}"
            st.session_state.setdefault(m_key, st.session_state.get(side_key, pairs[0]))
            with cols[1] if cols[1] is not None else cols[0]:
                if len(pairs) <= 5:
                    st.segmented_control(
                        "Market",
                        pairs,
                        format_func=uni.display,
                        key=m_key,
                        on_change=_sync_state(m_key, side_key),
                        label_visibility="collapsed",
                    )
                else:  # ten markets: a select reads better than a wrapping tab row
                    st.selectbox(
                        "Market",
                        pairs,
                        format_func=uni.display,
                        key=m_key,
                        on_change=_sync_state(m_key, side_key),
                        label_visibility="collapsed",
                    )
        hint = (
            "Episode replay, the as-of date and the other pages live in the side panel (» top left)."
            if pairs
            else "The other pages live in the side panel (» top left)."
        )
        st.markdown(f'<div class="fx-mobile-hint">{hint}</div>', unsafe_allow_html=True)


# ---- shared scenario controls (Overview + Advisor) ------------------------------------------
def scenario_controls(uni, pairs: list[str], regimes_all: pd.DataFrame):
    """Sidebar: pair, named-episode jump, free 'as of' date. Deep links: ?pair=&asof=.
    Returns (pair, as_of Timestamp, time_machine bool, episode label)."""
    latest_date = regimes_all["date"].max()
    episodes: dict[str, tuple | None] = {"today (latest data)": None}
    for p, events in uni.known_events.items():
        for d, label in events:
            episodes[f"{label} — {uni.display(p)} {d}"] = (pd.Timestamp(d), p)
    qp = st.query_params if hasattr(st, "query_params") else {}
    qp_pair = qp.get("pair") if qp.get("pair") in pairs else None
    try:
        qp_asof = pd.Timestamp(qp.get("asof")) if qp.get("asof") else None
    except Exception:
        qp_asof = None
    with st.sidebar:
        st.markdown('<div class="fx-side-h">Market</div>', unsafe_allow_html=True)
        side_key = f"pair_{uni.name}"
        st.session_state.setdefault(side_key, qp_pair or pairs[0])
        if st.session_state[side_key] not in pairs:
            st.session_state[side_key] = pairs[0]
        pair = st.selectbox(
            "Pair",
            pairs,
            format_func=uni.display,
            key=side_key,
            on_change=_sync_state(side_key, f"m_pair_{uni.name}"),
        )
        st.markdown('<div class="fx-side-h">Scenario explorer</div>', unsafe_allow_html=True)
        episode = st.selectbox(
            "Jump to an episode", list(episodes), index=0, key=f"episode_{uni.name}"
        )
        ep = episodes[episode]
        use_link = qp_asof is not None and not st.session_state.get("_asof_from_url")
        default_date = (ep[0] if ep else (qp_asof if use_link else latest_date)).date()
        if qp_asof is not None:
            st.session_state["_asof_from_url"] = True
        as_of_date = st.date_input(
            "or pick an 'as of' date",
            value=default_date,
            key=f"asof_{uni.name}_{episode}_{qp_asof.date() if qp_asof is not None else ''}",
            min_value=(regimes_all["date"].min() + pd.Timedelta(days=30)).date(),
            max_value=latest_date.date(),
        )
        st.caption("Everything is filtered/causal, so any past date can be replayed honestly.")
    as_of = min(pd.Timestamp(as_of_date), latest_date)
    st.session_state["scenario"] = {"pair": pair, "as_of": str(as_of.date()), "episode": episode}
    return pair, as_of, as_of < latest_date, episode


def grid(items: list, per_row: int = 3):
    """Yield (column, item) pairs laid out in rows of `per_row` — so a universe with ten markets
    gets ten readable cards in rows instead of ten slivers in one row."""
    items = list(items)
    for start in range(0, len(items), per_row):
        chunk = items[start : start + per_row]
        cols = st.columns(per_row)
        yield from zip(cols, chunk, strict=False)


def market_table(rows: list[dict]) -> str:
    """Dense market overview for large universes: one line per market — regime pill, confidence,
    age, change risk with band, consensus, siren, last close and a 20-day sparkline. Numbers in a
    well-set table read faster than ten cards (and never colour-only: word + dot)."""
    head = (
        "<tr><th>market</th><th style='text-align:left'>regime</th><th>conf.</th><th>day</th>"
        "<th>5-day change risk</th><th>90 % band</th><th>consensus</th><th>siren</th>"
        "<th>close</th><th style='text-align:left'>20 days</th></tr>"
    )
    body = []
    for r in rows:
        color = REGIME_COLORS.get(r["regime"], MUTED)
        band = (
            f'{r["risk_lo"] * 100:.0f}–{r["risk_hi"] * 100:.0f}%'
            if r.get("risk_lo") is not None and r.get("risk_hi") is not None
            else "—"
        )
        votes = ""
        if r.get("agreement") is not None:
            lvl = int(r["agreement"])
            vcol = (
                REGIME_COLORS["crisis"]
                if lvl == 3
                else REGIME_COLORS["chop"] if lvl == 2 else MUTED
            )
            votes = f'<span class="fx-num" style="color:{vcol}">{lvl}/3</span>'
        siren = r.get("anomaly_pct")
        siren_html = (
            f'<span style="color:{siren_color(float(siren))}">{float(siren):.0f}</span>'
            if siren is not None and siren == siren
            else "—"
        )
        body.append(
            "<tr>"
            f'<td class="fx-num" style="text-align:left;font-family:{FONT_UI};font-weight:500">{html.escape(r["label"])}</td>'
            f'<td style="text-align:left">{regime_pill(r["regime"])}</td>'
            f'<td>{r["regime_prob"] * 100:.0f}%</td>'
            f'<td>{int(r["days_in_regime"])}</td>'
            f'<td style="color:{risk_color(r["change_risk"])}">{r["change_risk"] * 100:.0f}%</td>'
            f"<td>{band}</td><td>{votes}</td><td>{siren_html}</td>"
            f'<td>{r["close"]}</td>'
            f'<td style="text-align:left">{sparkline_svg(r["closes"], color, width=120, height=26)}</td>'
            "</tr>"
        )
    return (
        f'<div class="fx-table-wrap"><table class="fx-table"><thead>{head}</thead><tbody>'
        + "".join(body)
        + "</tbody></table></div>"
    )


def kpi(label: str, value: str, sub: str = "", color: str = TEXT) -> str:
    """One KPI tile (HTML) for the strip at the top of a page."""
    return (
        f'<div class="fx-kpi"><div class="fx-kpi-l">{html.escape(label)}</div>'
        f'<div class="fx-kpi-v fx-num" style="color:{color}">{value}</div>'
        f'<div class="fx-kpi-s">{sub}</div></div>'
    )


def kpi_strip(tiles: list[str]) -> None:
    st.markdown('<div class="fx-kpis">' + "".join(tiles) + "</div>", unsafe_allow_html=True)


def stability_color(score: float) -> str:
    return (
        REGIME_COLORS["calm"]
        if score >= 75
        else (
            REGIME_COLORS["trend"]
            if score >= 55
            else (REGIME_COLORS["chop"] if score >= 35 else REGIME_COLORS["crisis"])
        )
    )


def gauge_svg(score: float, size: int = 120, label: str = "") -> str:
    """Semi-circular gauge for a 0..100 score, coloured by band."""
    score = max(0.0, min(100.0, float(score)))
    color = stability_color(score)
    r = size * 0.42
    cx, cy = size / 2, size * 0.58
    import math

    def pt(a):
        return cx + r * math.cos(math.pi * (1 - a)), cy - r * math.sin(math.pi * (1 - a))

    x0, y0 = pt(0.0)
    x1, y1 = pt(score / 100.0)
    xe, ye = pt(1.0)
    large = 1 if score > 50 else 0
    return (
        f'<svg width="{size}" height="{size * 0.66}" viewBox="0 0 {size} {size * 0.66}">'
        f'<path d="M {x0:.1f} {y0:.1f} A {r:.1f} {r:.1f} 0 1 1 {xe:.1f} {ye:.1f}" fill="none" stroke="{BORDER}" stroke-width="{size * 0.08:.1f}" stroke-linecap="round"/>'
        + (
            f'<path d="M {x0:.1f} {y0:.1f} A {r:.1f} {r:.1f} 0 {large} 1 {x1:.1f} {y1:.1f}" fill="none" stroke="{color}" stroke-width="{size * 0.08:.1f}" stroke-linecap="round"/>'
            if score > 0.5
            else ""
        )
        + f'<text x="{cx}" y="{cy - 2}" text-anchor="middle" font-family="IBM Plex Mono, monospace" font-size="{size * 0.2:.0f}" fill="{TEXT}">{score:.0f}</text>'
        f'<text x="{cx}" y="{cy + size * 0.13:.1f}" text-anchor="middle" font-family="IBM Plex Sans, sans-serif" font-size="{size * 0.09:.0f}" fill="{MUTED}">{html.escape(label)}</text></svg>'
    )


# ---- signature structures (phase 31) ------------------------------------------------------------
def live_dot(label: str) -> str:
    """'● live · day N' — the only motion besides the orb (slow pulse, off under reduced-motion)."""
    return f'<span class="fx-live"><span class="fx-dot"></span>{html.escape(label)}</span>'


def risk_trace_svg(
    risk: pd.Series,
    lo: pd.Series | None,
    hi: pd.Series | None,
    color: str,
    width: int = 920,
    height: int = 56,
) -> str:
    """The quiet 90-day change-risk trace with its shaded band (inline SVG, no axes on purpose)."""
    r = pd.Series(risk).astype(float).dropna()
    if len(r) < 2:
        return ""
    n = len(r)
    xs = [i * width / (n - 1) for i in range(n)]

    def y(v: float) -> float:
        v = max(0.0, min(1.0, float(v)))
        return height - 4 - v * (height - 8)

    line = " ".join(f"{x:.1f},{y(v):.1f}" for x, v in zip(xs, r, strict=True))
    poly = ""
    if lo is not None and hi is not None:
        lo_s = pd.Series(lo).astype(float).reindex(r.index).ffill().fillna(0.0)
        hi_s = pd.Series(hi).astype(float).reindex(r.index).ffill().fillna(0.0)
        top = " ".join(f"{x:.1f},{y(v):.1f}" for x, v in zip(xs, hi_s, strict=True))
        bottom = " ".join(
            f"{x:.1f},{y(v):.1f}" for x, v in zip(reversed(xs), reversed(list(lo_s)), strict=True)
        )
        poly = f'<polygon points="{top} {bottom}" fill="{color}" fill-opacity="0.07"/>'
    y_thr = y(0.22)  # the frozen alarm threshold, as a hairline reference
    x_end, y_end = xs[-1], y(float(r.iloc[-1]))
    return (
        f'<svg class="fx-trace" viewBox="0 0 {width} {height}" width="100%" height="{height}" role="img" '
        f'aria-label="Ninety-day change-risk trace with its uncertainty band" preserveAspectRatio="none">'
        f'<line x1="0" y1="{y_thr:.1f}" x2="{width}" y2="{y_thr:.1f}" stroke="{DIM}" stroke-width="0.8" stroke-dasharray="3 4" opacity="0.7"/>'
        f'{poly}<polyline points="{line}" fill="none" stroke="{color}" stroke-width="1.5" vector-effect="non-scaling-stroke"/>'
        f'<circle class="fx-now" cx="{x_end:.1f}" cy="{y_end:.1f}" r="3" fill="{color}"/>'
        f'<circle cx="{x_end:.1f}" cy="{y_end:.1f}" r="1.4" fill="{color}"/></svg>'
        f'<div class="fx-trace-axis"><span>90 days ago</span><span>alarm line 0.22</span><span>today</span></div>'
    )


def condition_banner(
    pair_label: str,
    data_through: str,
    regime: str,
    change_risk: float | None,
    lo: float | None,
    hi: float | None,
    siren_pct: float | None,
    agreement: int | None = None,
    votes: dict | None = None,
    trace: str = "",
    eyebrow_extra: str = "",
) -> None:
    """Signature 1 — the condition banner: the full market state readable in three seconds from two
    metres. Eyebrow (pair + data-through), the regime word huge in its colour, one metrics line,
    the quiet risk trace, and the three-dot consensus module."""
    color = REGIME_COLORS.get(regime, MUTED)
    metrics = []
    if change_risk is not None and change_risk == change_risk:
        band = (
            f' <span class="fx-dim">({float(lo):.2f}–{float(hi):.2f} · 90% band)</span>'
            if lo is not None and hi is not None and lo == lo and hi == hi
            else ""
        )
        metrics.append(f"change risk {float(change_risk):.2f}{band}")
    if siren_pct is not None and siren_pct == siren_pct:
        metrics.append(f'siren {float(siren_pct):.0f}<span class="fx-dim">/100</span>')
    consensus = ""
    if agreement is not None and agreement == agreement:
        votes = votes or {}
        pips = "".join(
            f'<span><span class="fx-pip" style="{("background:" + color + ";border-color:" + color) if int(votes.get(k, 0) or 0) else ""}"></span>{lbl}</span>'
            for lbl, k in (("HMM", "vote_hmm"), ("BOCPD", "vote_bocpd"), ("vol rule", "vote_vol"))
        )
        consensus = f'<div class="fx-consensus">consensus {int(agreement)}/3<div class="fx-votes">{pips}</div></div>'
    st.markdown(
        f'<section class="fx-banner" aria-label="current condition">'
        f'<div class="fx-eyebrow">{html.escape(pair_label)} · current condition · data through {html.escape(data_through)}{eyebrow_extra}</div>'
        f'<div class="fx-condrow"><div><div class="fx-cond" style="color:{color}">{html.escape(regime.capitalize())}</div>'
        f'<div class="fx-metrics">{" · ".join(metrics)}</div></div>{consensus}</div>{trace}</section>',
        unsafe_allow_html=True,
    )


@st.cache_data(show_spinner=False)
def _trust_numbers(data_dir: str, mtimes: tuple) -> dict:
    """Small artifact reads for the trust strip (cached on file mtimes)."""
    d = Path(data_dir)
    out: dict = {}
    for name, key in (
        ("live_record.json", "live"),
        ("conformal_coverage.json", "coverage"),
        ("status.json", "status"),
    ):
        p = d / name
        out[key] = json.loads(p.read_text()) if p.exists() else {}
    head = d / "ledger_head.txt"
    out["head"] = head.read_text().split() if head.exists() else []
    return out


def trust_strip(data_dir: Path | str | None = None, proof_href: str = "proof") -> None:
    """Signature 2 — the trust strip: forward-test day count, live Brier vs frozen, coverage vs
    target, chain head + check, and the 'verify independently' link. Mono. Never below the fold."""
    from fxradar import config

    d = Path(data_dir) if data_dir else config.DATA_DIR
    files = ("live_record.json", "conformal_coverage.json", "status.json", "ledger_head.txt")
    mtimes = tuple(os.path.getmtime(d / f) if (d / f).exists() else -1.0 for f in files)
    t = _trust_numbers(str(d), mtimes)
    live, cov, head = t["live"], t["coverage"], t["head"]
    if not live:
        st.markdown(
            '<div class="fx-trust"><span>forward test not started — the first daily run writes the ledger</span>'
            f'<a href="{proof_href}" target="_self">verify independently ↗</a></div>',
            unsafe_allow_html=True,
        )
        return
    m = live.get("metrics") or {}
    fz = live.get("frozen_test") or {}
    days = live.get("days_recorded", 0)
    brier = (
        f"Brier {m['brier']:.3f} <span class=\"fx-dim\">vs {fz.get('brier', float('nan')):.3f} frozen</span>"
        if m.get("brier") is not None
        else f"Brier <span class=\"fx-dim\">warming up · {live.get('n_resolved', 0)}/{live.get('min_resolved', 20)} resolved</span>"
    )
    live_cov = (cov.get("live") or {}).get("coverage")
    test_cov = (cov.get("frozen_test") or {}).get("overall")
    coverage = (
        f'coverage {live_cov:.0%} <span class="fx-dim">vs 90 target</span>'
        if live_cov is not None
        else (
            f'coverage {test_cov:.1%} <span class="fx-dim">frozen · target 90</span>'
            if test_cov is not None
            else ""
        )
    )
    head_hash = head[0] if head else live.get("head_hash", "")
    ok = bool(live.get("chain_ok"))
    chain = (
        f'chain {head_hash[:4]}…{head_hash[-2:]} <span style="color:{REGIME_COLORS["calm"] if ok else REGIME_COLORS["crisis"]}">{"✓" if ok else "✗"}</span>'
        if head_hash
        else ""
    )
    parts = " · ".join(x for x in (f"forward test day {days}", brier, coverage, chain) if x)
    st.markdown(
        f'<div class="fx-trust"><span class="fx-num">{parts}</span>'
        f'<a href="{proof_href}" target="_self">verify independently ↗</a></div>',
        unsafe_allow_html=True,
    )


def state(title: str, what_happened: str, what_to_do: str) -> None:
    """Empty / loading / error state with directive copy: say what happened and what to do."""
    st.markdown(
        f'<div class="fx-state"><b>{html.escape(title)}</b><br>{html.escape(what_happened)} '
        f"{html.escape(what_to_do)}</div>",
        unsafe_allow_html=True,
    )
