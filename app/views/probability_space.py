"""Probability space — the regime tetrahedron and the market landscape (display layer only).

(A) The HMM's four FILTERED probabilities sum to one, so each day is a point in a tetrahedron whose
    corners are the regimes; the market's history is a path through it.
(B) A PCA(3) embedding of the day-level features, fit on train rows only, applied to all history.

Reads artifacts and frozen model files only (rule 8): the four probabilities are replayed from the
frozen bundle's forward filter (the same causal function the pipeline used) and cached; the
embedding was fit offline (`python -m fxradar.viz3d --fit`) and is loaded here, never fit here.
Every other page stays 2-D on purpose.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ui  # noqa: E402
from fxradar import viz3d  # noqa: E402
from fxradar.config import DISCLAIMER  # noqa: E402

ui.sidebar(DISCLAIMER)
UNI_NAME, UNI, DIRS = ui.universe_selector()
PAIRS = list(UNI.pairs)
DATA, MODELS = DIRS["data"], DIRS["models"]


def _mtime(p: Path) -> float:
    return os.path.getmtime(p) if p.exists() else -1.0


@st.cache_resource(show_spinner=False)
def _inputs(data_dir: str, models_dir: str, mtime_r: float, mtime_f: float):
    """features, regimes and frozen HMM bundles for one universe (cached per artifact version)."""
    return viz3d.load_inputs(Path(data_dir), Path(models_dir))


@st.cache_data(show_spinner=False)
def _prob_frame(data_dir: str, models_dir: str, mtime_r: float, mtime_f: float, pair: str):
    features, regimes, bundles = _inputs(data_dir, models_dir, mtime_r, mtime_f)
    return viz3d.probability_frame(pair, features, regimes, bundles[pair])


@st.cache_data(show_spinner=False)
def _land_frame(data_dir: str, models_dir: str, mtime_r: float, mtime_f: float, pair: str):
    features, regimes, _ = _inputs(data_dir, models_dir, mtime_r, mtime_f)
    return viz3d.landscape_frame(pair, features, regimes)


@st.cache_resource(show_spinner=False)
def _embedding(models_dir: str, pair: str, mtime: float):
    return viz3d.load_embedding(pair, Path(models_dir))


REGIMES_PATH, FEATURES_PATH = DATA / "regimes.parquet", DATA / "features.parquet"
if not (REGIMES_PATH.exists() and FEATURES_PATH.exists()):
    st.error("Artifacts missing — run the pipeline first (`make pipeline`).")
    st.stop()
MT_R, MT_F = _mtime(REGIMES_PATH), _mtime(FEATURES_PATH)

# --------------------------------------------------------------------------------------
# header + controls
# --------------------------------------------------------------------------------------
st.markdown(
    '<div class="fx-header"><div><span class="fx-wordmark">Probability space</span>'
    f'<span class="fx-sub">{UNI.label} · where the model\'s beliefs live</span></div></div>',
    unsafe_allow_html=True,
)
ui.mobile_bar()
c1, c2 = st.columns([1.4, 1], vertical_alignment="bottom")
with c1:
    pair = st.segmented_control(
        "Market", PAIRS, default=PAIRS[0], format_func=UNI.display, key=f"ps_pair_{UNI_NAME}"
    )
with c2:
    color_by = st.segmented_control(
        "Colour the path by",
        ["time", "siren"],
        default="time",
        format_func=lambda v: {"time": "time (dim → bright)", "siren": "anomaly siren"}[v],
        key="ps_color",
    )
pair = pair or PAIRS[0]
color_by = color_by or "time"

# --------------------------------------------------------------------------------------
# A) the tetrahedron
# --------------------------------------------------------------------------------------
st.markdown('<div class="fx-section">A · The regime tetrahedron</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="fx-muted" style="margin:-4px 0 6px 2px;max-width:900px">'
    "Each day the model holds four probabilities that add up to one, so every day is a single point "
    "inside this tetrahedron. A <b>corner</b> means the model is certain of one regime; the <b>centre</b> "
    "means it has no idea (¼ each); a point on an <b>edge</b> is torn between two regimes. The path is the "
    "market's history through those beliefs — filtered probabilities only, what was known on each day. "
    "The ringed marker is the latest day.</div>",
    unsafe_allow_html=True,
)
try:
    frame = _prob_frame(str(DATA), str(MODELS), MT_R, MT_F, pair)
except FileNotFoundError as exc:
    st.error(f"Frozen HMM bundle not found for this universe ({exc}).")
    st.stop()
fig_a = viz3d.tetrahedron_figure(frame, UNI.display(pair), color_by, template=ui.PLOTLY_TEMPLATE)
st.plotly_chart(fig_a, width="stretch", config={"displayModeBar": False, "scrollZoom": True})
last = frame.iloc[-1]
st.markdown(
    f'<div class="fx-muted" style="font-size:0.8rem;margin:-6px 0 4px 2px">Latest day {last["date"]:%Y-%m-%d}: '
    + " · ".join(
        f'{r} <span class="fx-num">{last[f"p_{r}"]:.2f}</span>' for r in viz3d.REGIME_ORDER
    )
    + f' · siren <span class="fx-num">{float(last["anomaly_pct"] or 0):.0f}</span>. '
    "Hover any point for its four probabilities.</div>",
    unsafe_allow_html=True,
)

# --------------------------------------------------------------------------------------
# B) the landscape
# --------------------------------------------------------------------------------------
st.markdown('<div class="fx-section">B · The market landscape</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="fx-muted" style="margin:-4px 0 6px 2px;max-width:900px">'
    "Every day described by its eight backward-looking features, squeezed to three axes by PCA that was "
    "fit on the training years only and then frozen — later days are placed by that fixed map, never "
    "refit. A <b>cluster</b> of one colour is a kind of day the model keeps naming the same way; days far "
    "from every cluster are unusual. The bright trail is the last 60 days walking across the landscape, "
    "the ringed marker is the latest day. Axes are principal components: unit-free, ranked by variance.</div>",
    unsafe_allow_html=True,
)
emb_path = viz3d.embedding_path(pair, MODELS)
if not emb_path.exists():
    st.info(
        "The landscape embedding has not been fit for this universe yet. Run "
        f"`{'FXRADAR_UNIVERSE=' + UNI_NAME + ' ' if UNI_NAME != 'fx' else ''}"
        "python -m fxradar.viz3d --fit` (offline, train rows only) — the app never fits it."
    )
else:
    emb = _embedding(str(MODELS), pair, _mtime(emb_path))
    lframe = _land_frame(str(DATA), str(MODELS), MT_R, MT_F, pair)
    fig_b = viz3d.landscape_figure(lframe, emb, UNI.display(pair), template=ui.PLOTLY_TEMPLATE)
    st.plotly_chart(fig_b, width="stretch", config={"displayModeBar": False, "scrollZoom": True})
    st.markdown(
        f'<div class="fx-muted" style="font-size:0.8rem;margin:-6px 0 4px 2px">Embedding fit on '
        f'<span class="fx-num">{emb.n_fit_rows:,}</span> train rows ≤ {emb.train_end}; explained variance '
        + ", ".join(f'<span class="fx-num">{v:.0%}</span>' for v in emb.explained)
        + " (three components of eight features). Nothing here predicts anything.</div>",
        unsafe_allow_html=True,
    )

ui.footer(
    DISCLAIMER,
    "Probability space is a display of numbers the pipeline already computed — filtered regime "
    "probabilities and a train-only PCA — and predicts nothing.",
)
