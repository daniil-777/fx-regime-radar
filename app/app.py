"""FX Regime Radar — dashboard. Reads small artifacts only (CLAUDE.md rule 8); no models here."""

from __future__ import annotations

import html
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(
    0, str(Path(__file__).resolve().parent)
)  # so `import ui` works under `streamlit run`
import ui  # noqa: E402
from fxradar.config import (
    DATA_DIR,
    DISCLAIMER,
    PAIRS,
    PRICES_PATH,
    REGIMES_PATH,
    REPORT_PATH,
    VAL_START,
)  # noqa: E402

STATUS_PATH = DATA_DIR / "pipeline_status.json"

st.set_page_config(
    page_title="FX Regime Radar", page_icon="📡", layout="wide", initial_sidebar_state="expanded"
)
ui.inject_css()

REGIME_ORDER = ["calm", "trend", "chop", "crisis"]


# --------------------------------------------------------------------------------------
# loaders: cached, keyed by file mtime so a fresh artifact invalidates the cache
# --------------------------------------------------------------------------------------
def _mtime(path: Path) -> float:
    return os.path.getmtime(path) if path.exists() else -1.0


@st.cache_data(show_spinner=False)
def load_regimes(mtime: float) -> pd.DataFrame:
    return pd.read_parquet(REGIMES_PATH)


@st.cache_data(show_spinner=False)
def load_prices(mtime: float) -> pd.DataFrame:
    return pd.read_parquet(PRICES_PATH)[["date", "pair", "close"]]


@st.cache_data(show_spinner=False)
def regime_runs(mtime: float, pair: str) -> pd.DataFrame:
    """Consecutive same-regime days merged into bands: regime, start, end (light pandas)."""
    r = load_regimes(mtime)
    g = r[r["pair"] == pair].sort_values("date").reset_index(drop=True)
    new_run = g["regime"].ne(g["regime"].shift(1)).cumsum()
    runs = g.groupby(new_run).agg(
        regime=("regime", "first"), start=("date", "first"), end=("date", "last")
    )
    # extend each band to the next band's start so there are no hairline gaps
    runs["end"] = runs["start"].shift(-1).fillna(runs["end"])
    return runs.reset_index(drop=True)


@st.cache_data(show_spinner=False)
def anatomy(mtime_r: float, mtime_p: float, pair: str) -> pd.DataFrame:
    """Out-of-sample regime anatomy for one pair (same definitions as reports/hmm_validation.md)."""
    r = load_regimes(mtime_r)
    p = load_prices(mtime_p)
    g = r[r["pair"] == pair].merge(p[p["pair"] == pair], on=["date", "pair"]).sort_values("date")
    g["ret"] = np.log(g["close"] / g["close"].shift(1))
    g = g[g["date"] >= pd.Timestamp(VAL_START)]
    new_run = g["regime"].ne(g["regime"].shift(1)).cumsum()
    run_len = g.groupby(new_run).agg(regime=("regime", "first"), length=("regime", "size"))
    rows = []
    for regime in REGIME_ORDER:
        rr = g.loc[g["regime"] == regime, "ret"].dropna()
        eq = np.exp(rr.cumsum())
        rows.append(
            {
                "regime": regime,
                "days": int(len(rr)),
                "share %": 100 * len(rr) / max(len(g), 1),
                "mean run (d)": (
                    float(run_len.loc[run_len["regime"] == regime, "length"].mean())
                    if len(rr)
                    else np.nan
                ),
                "ann. vol %": float(rr.std(ddof=1) * np.sqrt(252) * 100) if len(rr) > 1 else np.nan,
                "mean ret (bp)": float(rr.mean() * 1e4) if len(rr) else np.nan,
                "worst dd %": float((eq / eq.cummax() - 1).min() * 100) if len(rr) else np.nan,
            }
        )
    return pd.DataFrame(rows)


@st.cache_data(show_spinner=False)
def load_status(mtime: float) -> dict:
    return json.loads(STATUS_PATH.read_text()) if STATUS_PATH.exists() else {}


@st.cache_data(show_spinner=False)
def load_report(mtime: float) -> dict:
    return json.loads(REPORT_PATH.read_text()) if REPORT_PATH.exists() else {}


regimes = load_regimes(_mtime(REGIMES_PATH))
prices = load_prices(_mtime(PRICES_PATH))
status = load_status(_mtime(STATUS_PATH))
report = load_report(_mtime(REPORT_PATH))
data_through = regimes["date"].max()
updated = status.get("last_run_utc", "")
updated_txt = (
    f' · updated <span class="fx-num">{html.escape(updated[:16].replace("T", " "))} UTC</span>'
    if updated
    else ""
)

# --------------------------------------------------------------------------------------
# sidebar: pair selector + disclaimer only
# --------------------------------------------------------------------------------------
ui.sidebar(DISCLAIMER)
with st.sidebar:
    pair = st.selectbox("Pair", PAIRS, index=0)

# --------------------------------------------------------------------------------------
# header
# --------------------------------------------------------------------------------------
st.markdown(
    f'<div class="fx-header"><div><span class="fx-wordmark">FX Regime Radar</span>'
    f'<span class="fx-sub">market weather, updated daily</span></div>'
    f'<div class="fx-right">Data through <span class="fx-num">{data_through:%Y-%m-%d}</span>{updated_txt}</div></div>',
    unsafe_allow_html=True,
)

# --------------------------------------------------------------------------------------
# hero row: one weather card per pair
# --------------------------------------------------------------------------------------
cols = st.columns(len(PAIRS))
for col, p in zip(cols, PAIRS, strict=True):
    latest = regimes[regimes["pair"] == p].sort_values("date").iloc[-1]
    color = ui.REGIME_COLORS[latest["regime"]]
    closes = prices[prices["pair"] == p].sort_values("date")["close"].tail(20)
    body = (
        f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">'
        f'<span style="font-weight:600;font-size:1.05rem">{p[:3]}/{p[3:]}</span>{ui.regime_pill(latest["regime"], large=True)}</div>'
        f'<div class="fx-muted" style="font-size:0.82rem;margin-bottom:6px">{ui.REGIME_BLURB[latest["regime"]]}</div>'
        f"{ui.confidence_bar(latest['regime_prob'], color)}"
        f'<div class="fx-kv" style="margin-top:6px"><span>day <span class="fx-num">{int(latest["days_in_regime"])}</span> of this regime</span>'
        f'<span>last close <span class="fx-num">{closes.iloc[-1]:.4f}</span></span></div>'
        f"{ui.sparkline_svg(closes, color)}"
        f'<div class="fx-kv"><span>20-day close</span><span class="fx-num">{(closes.iloc[-1] / closes.iloc[0] - 1) * 100:+.2f}%</span></div>'
        + (
            ui.risk_gauge(latest["change_risk_5d"], list(latest["top_drivers"]))
            if "change_risk_5d" in latest and pd.notna(latest["change_risk_5d"])
            else ""
        )
        + ui.narration(report.get(p))
    )
    with col:
        ui.card(body)

# --------------------------------------------------------------------------------------
# main panel: close with regime bands
# --------------------------------------------------------------------------------------
g = prices[prices["pair"] == pair].sort_values("date")
runs = regime_runs(_mtime(REGIMES_PATH), pair)
fig = go.Figure()
fig.add_trace(
    go.Scatter(
        x=g["date"],
        y=g["close"],
        mode="lines",
        name="close",
        line=dict(color=ui.TEXT, width=1.1),
        hovertemplate="%{x|%Y-%m-%d}<br>%{y:.4f}<extra></extra>",
    )
)
shapes = [
    dict(
        type="rect",
        xref="x",
        yref="paper",
        x0=r.start,
        x1=r.end,
        y0=0,
        y1=1,
        fillcolor=ui.REGIME_COLORS[r.regime],
        opacity=0.28,
        line_width=0,
        layer="below",
    )
    for r in runs.itertuples(index=False)
]
divider = pd.Timestamp(VAL_START)
shapes.append(
    dict(
        type="line",
        xref="x",
        yref="paper",
        x0=divider,
        x1=divider,
        y0=0,
        y1=1,
        line=dict(color=ui.MUTED, width=1, dash="dash"),
    )
)
fig.update_layout(
    template=ui.PLOTLY_TEMPLATE,
    shapes=shapes,
    height=430,
    margin=dict(l=40, r=20, t=30, b=40),
    annotations=[
        dict(
            x=divider,
            y=1.02,
            xref="x",
            yref="paper",
            text="out-of-sample →",
            showarrow=False,
            font=dict(color=ui.MUTED, size=11),
            xanchor="left",
        )
    ],
    xaxis=dict(
        rangeselector=dict(
            buttons=[
                dict(count=1, label="1y", step="year", stepmode="backward"),
                dict(count=3, label="3y", step="year", stepmode="backward"),
                dict(step="all", label="max"),
            ],
            bgcolor=ui.SURFACE,
            activecolor=ui.BORDER,
            bordercolor=ui.BORDER,
            font=dict(color=ui.TEXT),
        ),
    ),
    yaxis=dict(fixedrange=False),
    showlegend=False,
)
# legend pills for the bands
legend = " ".join(ui.regime_pill(r) for r in REGIME_ORDER)
st.markdown(
    f'<div style="display:flex;justify-content:space-between;align-items:center;margin:6px 0 -4px 2px">'
    f'<span style="font-weight:600">{pair[:3]}/{pair[3:]} — close with filtered regime bands</span><span>{legend}</span></div>',
    unsafe_allow_html=True,
)
st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

# --------------------------------------------------------------------------------------
# regime anatomy (out of sample)
# --------------------------------------------------------------------------------------
an = anatomy(_mtime(REGIMES_PATH), _mtime(PRICES_PATH), pair)
an_html = ui.html_table(
    an,
    {
        "share %": "{:.1f}",
        "mean run (d)": "{:.0f}",
        "ann. vol %": "{:.1f}",
        "mean ret (bp)": "{:+.1f}",
        "worst dd %": "{:.1f}",
    },
)
an_html = (
    an_html.replace("<td>calm</td>", f"<td>{ui.regime_pill('calm')}</td>")
    .replace("<td>trend</td>", f"<td>{ui.regime_pill('trend')}</td>")
    .replace("<td>chop</td>", f"<td>{ui.regime_pill('chop')}</td>")
    .replace("<td>crisis</td>", f"<td>{ui.regime_pill('crisis')}</td>")
)
ui.card(
    f'<div class="fx-muted" style="font-size:0.82rem;margin-bottom:8px">Out-of-sample since {html.escape(VAL_START)} — how each label has behaved once the model could no longer see the data. Regimes describe conditions, not direction.</div>{an_html}',
    title=f"Regime anatomy — {pair[:3]}/{pair[3:]}",
)

# --------------------------------------------------------------------------------------
# anomaly siren
# --------------------------------------------------------------------------------------
if "anomaly_pct" in regimes.columns:
    st.markdown(
        '<div style="font-weight:600;margin:6px 0 8px 2px">Anomaly siren — how unlike a calm day is today?</div>',
        unsafe_allow_html=True,
    )
    scols = st.columns(len(PAIRS))
    for col, p in zip(scols, PAIRS, strict=True):
        g = regimes[regimes["pair"] == p].sort_values("date")
        latest = g.iloc[-1]
        two_years = g[g["date"] >= g["date"].max() - pd.DateOffset(years=2)]
        body = ui.siren_dial(latest["anomaly_pct"], f"{p[:3]}/{p[3:]}") + ui.sparkline_svg(
            two_years["anomaly_pct"], ui.siren_color(latest["anomaly_pct"]), width=300, height=40
        )
        body += (
            '<div class="fx-kv"><span>2-year anomaly percentile</span><span class="fx-num">'
            + f'{two_years["anomaly_pct"].iloc[-1]:.0f}'
            + "</span></div>"
        )
        with col:
            ui.card(body)
    loud = (
        regimes[regimes["pair"] == pair]
        .nlargest(8, "anomaly_score")[["date", "regime", "anomaly_score", "anomaly_pct"]]
        .copy()
    )
    loud["date"] = loud["date"].dt.strftime("%Y-%m-%d")
    loud = loud.rename(columns={"anomaly_score": "score", "anomaly_pct": "percentile"})
    ui.card(
        '<div class="fx-muted" style="font-size:0.82rem;margin-bottom:8px">The days the autoencoder found hardest to reconstruct — history the model never learnt as "normal". Detection only: nothing here predicts.</div>'
        + ui.html_table(loud, {"score": "{:.2f}", "percentile": "{:.1f}"}),
        title=f"Loudest days in history — {pair[:3]}/{pair[3:]}",
    )

ui.footer(DISCLAIMER, "· Regimes are filtered (causal) HMM states; see Methodology.")
