"""Model lab — click between regime models and see how the same history reads under each lens.

Reads artifacts only (CLAUDE.md rule 8): `data/model_lab.parquet` + `data/model_lab.json`, both
written by `make model-lab`. The page computes nothing beyond band-building; the shipped record
and the live ledger always run on the champion — this page is the research bench beside it.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ui  # noqa: E402
from fxradar.config import DISCLAIMER  # noqa: E402

MODEL_LABELS = {
    "hmm": "HMM (champion)",
    "jump": "Jump model (research)",
    "gmm": "GMM — no persistence (research)",
}

ui.sidebar(DISCLAIMER)
UNI_NAME, UNI, DIRS = ui.universe_selector()
PAIRS = list(UNI.pairs)
DATA_DIR = DIRS["data"]
LAB_PARQUET, LAB_JSON = DATA_DIR / "model_lab.parquet", DATA_DIR / "model_lab.json"
PRICES_PATH = DATA_DIR / "prices.parquet"


def _mtime(path: Path) -> float:
    return os.path.getmtime(path) if path.exists() else -1.0


@st.cache_data(show_spinner=False)
def load_lab(path: str, mtime: float) -> pd.DataFrame:
    return pd.read_parquet(path)


@st.cache_data(show_spinner=False)
def load_json(path: str, mtime: float) -> dict:
    p = Path(path)
    return json.loads(p.read_text()) if p.exists() else {}


@st.cache_data(show_spinner=False)
def load_prices(path: str, mtime: float) -> pd.DataFrame:
    return pd.read_parquet(path)[["date", "pair", "close"]]


st.markdown(
    '<div class="fx-header"><div><span class="fx-wordmark">Model lab</span>'
    '<span class="fx-sub">the same history under three regime lenses — research bench, not the record</span></div>'
    f'<div class="fx-right">{UNI.label}</div></div>',
    unsafe_allow_html=True,
)
ui.mobile_bar(UNI, PAIRS)

if not (LAB_PARQUET.exists() and PRICES_PATH.exists()):
    ui.state(
        "No model-lab artifacts for this universe yet.",
        "This page reads files the lab writes; it never trains anything itself.",
        f"Run `make model-lab UNIVERSE={UNI_NAME}` once, then reload.",
    )
    ui.footer(DISCLAIMER)
    st.stop()

lab = load_lab(str(LAB_PARQUET), _mtime(LAB_PARQUET))
meta = load_json(str(LAB_JSON), _mtime(LAB_JSON))
prices = load_prices(str(PRICES_PATH), _mtime(PRICES_PATH))
models = [m for m in ("hmm", "jump", "gmm") if m in set(lab["model"])]

# ---- the two clicks: which lens, which market --------------------------------------------------
c1, c2 = st.columns([2, 1])
with c1:
    model = st.segmented_control(
        "Regime model",
        models,
        format_func=lambda m: MODEL_LABELS.get(m, m),
        default="hmm",
        key="lab_model",
    )
with c2:
    pair = st.selectbox("Market", PAIRS, format_func=UNI.display, key="lab_pair")
model = model or "hmm"

note = (meta.get("model_notes") or {}).get(model, "")
lam = (meta.get("lambda") or {}).get(pair)
badge = f" · λ = {lam:g}" if (model == "jump" and lam is not None) else ""
st.markdown(
    f'<div class="fx-muted" style="font-size:0.84rem;margin:-2px 0 8px 2px">{note}{badge}. '
    "The live ledger and every published forecast run on the champion; research lenses exist to be "
    "compared, not believed.</div>",
    unsafe_allow_html=True,
)

# ---- price with the selected model's regime bands ----------------------------------------------
sel = lab[(lab["model"] == model) & (lab["pair"] == pair)].sort_values("date")
px = prices[prices["pair"] == pair].sort_values("date")
runs = ui.runs_from_labels(sel["date"], sel["regime"])
downsampled = False
if len(runs) > 350:  # a flickery lens (GMM) would mean thousands of Plotly shapes — Plotly
    # validates each one, so the tint uses the WEEKLY MAJORITY label instead (identical to the eye
    # at a 21-year zoom; the anatomy table below carries the true daily switch counts).
    wk = (
        sel.set_index("date")["regime"]
        .resample("W")
        .agg(lambda x: x.mode().iloc[0] if len(x) else None)
        .dropna()
    )
    runs = ui.runs_from_labels(pd.Series(wk.index), wk.reset_index(drop=True))
    downsampled = True
fig = go.Figure()
fig.add_trace(
    go.Scatter(
        x=px["date"],
        y=px["close"],
        mode="lines",
        line=dict(color=ui.TEXT, width=1.0),
        hovertemplate="%{x|%Y-%m-%d}<br>%{y}<extra></extra>",
    )
)
oos = meta.get("oos_start")
shapes = ui.regime_bands(runs)
if oos:
    shapes.append(
        dict(
            type="line",
            xref="x",
            yref="paper",
            x0=oos,
            x1=oos,
            y0=0,
            y1=1,
            line=dict(color=ui.MUTED, width=1, dash="dash"),
        )
    )
legend = " ".join(ui.regime_pill(r) for r in ["calm", "trend", "chop", "crisis"])
st.markdown(
    f'<div style="display:flex;justify-content:space-between;align-items:center;margin:0 0 -4px 2px">'
    f'<span style="font-weight:500">{UNI.display(pair)} — close under {MODEL_LABELS[model]}'
    + (
        ' <span class="fx-dim" style="font-weight:400;font-size:0.76rem">(tint at weekly majority — this lens flickers daily; true counts below)</span>'
        if downsampled
        else ""
    )
    + "</span>"
    f"<span>{legend}</span></div>",
    unsafe_allow_html=True,
)
fig.update_layout(
    template=ui.PLOTLY_TEMPLATE,
    shapes=shapes,
    height=380,
    margin=dict(l=40, r=20, t=24, b=36),
    yaxis=dict(tickformat=",.5~g", type="log" if UNI.name == "crypto" else "linear"),
    showlegend=False,
)
st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

# ---- all three lenses stacked for this pair (one heatmap — fast, no shape explosion) ------------
CODE = {"calm": 0, "trend": 1, "chop": 2, "crisis": 3}
wide = (
    lab[lab["pair"] == pair]
    .pivot_table(index="model", columns="date", values="regime", aggfunc="first")
    .reindex(models)
)
z = wide.apply(lambda row: row.map(CODE)).to_numpy(dtype=float)
scale = []
for i, r in enumerate(["calm", "trend", "chop", "crisis"]):
    scale += [[i / 4, ui.REGIME_COLORS[r]], [(i + 1) / 4, ui.REGIME_COLORS[r]]]
ribbons = go.Figure(
    go.Heatmap(
        z=z,
        x=list(wide.columns),
        y=[MODEL_LABELS[m] for m in models],
        colorscale=scale,
        zmin=-0.5,
        zmax=3.5,
        showscale=False,
        hovertemplate="%{y}<br>%{x|%Y-%m-%d}: %{customdata}<extra></extra>",
        customdata=wide.to_numpy(),
    )
)
ribbons.update_layout(
    template=ui.PLOTLY_TEMPLATE,
    height=54 + 40 * len(models),
    margin=dict(l=10, r=20, t=8, b=28),
    yaxis=dict(autorange="reversed", showgrid=False),
    xaxis=dict(showgrid=False),
)
st.plotly_chart(ribbons, width="stretch", config={"displayModeBar": False})
st.markdown(
    '<div class="fx-dim" style="font-size:0.72rem;margin:-8px 0 10px 2px">one row per lens, same days — where the rows disagree is where the model choice matters; the GMM row\'s flicker is what the persistence machinery (transition matrix / jump penalty) removes</div>',
    unsafe_allow_html=True,
)

# ---- anatomy per model + forecaster engines -----------------------------------------------------
left, right = st.columns([1.15, 1])
with left:
    stats = (meta.get("stats") or {}).get(model, [])
    if stats:
        tbl = pd.DataFrame(stats)
        tbl = tbl.rename(
            columns={
                "share_calm": "calm %",
                "share_crisis": "crisis %",
                "mean_run_d": "mean run (d)",
                "switches_yr": "switches/yr",
                "vol_ordering_ok": "vol order ok",
                "vol_calm": "vol calm %",
                "vol_crisis": "vol crisis %",
            }
        )
        tbl["calm %"] = (tbl["calm %"] * 100).round(0)
        tbl["crisis %"] = (tbl["crisis %"] * 100).round(1)
        agree = (meta.get("agreement") or {}).get(model)
        ui.card(
            ui.html_table(
                tbl,
                {
                    "mean run (d)": "{:.0f}",
                    "switches/yr": "{:.1f}",
                    "vol calm %": "{:.1f}",
                    "vol crisis %": "{:.1f}",
                    "calm %": "{:.0f}",
                    "crisis %": "{:.1f}",
                },
            )
            + '<div class="fx-dim" style="font-size:0.76rem;margin-top:6px">out of sample since '
            + str(meta.get("oos_start", ""))
            + (
                f" · label agreement with the champion {agree:.0%}"
                if agree is not None and model != "hmm"
                else ""
            )
            + " · «vol order ok» = calm is still the lowest-volatility label out of sample</div>",
            title=f"Anatomy — {MODEL_LABELS[model]}",
        )
with right:
    engines = meta.get("forecasters") or []
    if engines:
        rows = [
            {
                "engine": e["estimator"],
                "thr": e["threshold"],
                "val PR-AUC": e["val"]["pr_auc"],
                "test PR-AUC": e["test"]["pr_auc"],
                "test Brier": e["test"]["brier"],
            }
            for e in engines
        ]
        ui.card(
            ui.html_table(
                pd.DataFrame(rows),
                {
                    "thr": "{:.2f}",
                    "val PR-AUC": "{:.3f}",
                    "test PR-AUC": "{:.3f}",
                    "test Brier": "{:.4f}",
                },
            )
            + '<div class="fx-dim" style="font-size:0.76rem;margin-top:6px">same matrix, same protocol '
            "(Platt on validation, recall-targeted threshold, frozen test scored once). Promotion of any "
            "engine goes through the challenger-ledger protocol — never a flag flip.</div>",
            title="Forecaster engines — never accuracy",
        )

ui.footer(
    DISCLAIMER,
    "· Research bench: the shipped record runs on the champion; full method in reports/model_lab.md.",
)
