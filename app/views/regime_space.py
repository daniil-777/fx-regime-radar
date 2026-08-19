"""Regime space — the HMM's feature space in 3D: where history lives, where today sits, how it moved.

Why 3D here and nowhere else: a hidden Markov model is, at heart, a clustering of days in feature
space with memory. Three of those features ARE the axes (realised vol, 20-day momentum, and a third
axis you choose), so depth is a real dimension — not a decorated time series. Two views:

* the state-space portrait — every day as a point coloured by its filtered regime, the last N days as
  a trail ending at today, playable through time;
* the regime landscape — a density terrain of history over (vol, momentum), coloured by the regime
  the model most often assigned there, with the same trail walking over the hills.

Everything is read from features.parquet + regimes.parquet (rule 8) and filtered to the as-of date, so
the scenario explorer replays honestly. Nothing here predicts; the geometry readout is descriptive.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ui  # noqa: E402
from fxradar.config import DISCLAIMER  # noqa: E402

REGIME_ORDER = ["calm", "trend", "chop", "crisis"]
REGIME_IDX = {r: i for i, r in enumerate(REGIME_ORDER)}
THIRD_AXES = {  # label -> (column, axis title, multiplier)
    "regime entropy (model doubt)": ("hmm_entropy", "HMM entropy (nats)", 1.0),
    "cross-pair correlation": ("corr_20", "20-day corr with the other pairs", 1.0),
    "vol ratio (20d / 60d)": ("vol_ratio", "vol_20 / vol_60", 1.0),
    "5-day change risk": ("change_risk_5d", "P(regime change, 5d)", 1.0),
    "days in regime": ("days_in_regime", "days since the regime last changed", 1.0),
}

ui.sidebar(DISCLAIMER)
UNI_NAME, UNI, DIRS = ui.universe_selector()
PAIRS = list(UNI.pairs)
DATA = DIRS["data"]
REGIMES_PATH, FEATURES_PATH = DATA / "regimes.parquet", DATA / "features.parquet"


def _mtime(p: Path) -> float:
    return os.path.getmtime(p) if p.exists() else -1.0


@st.cache_data(show_spinner=False)
def load_space(path_r: str, mtime_r: float, path_f: str, mtime_f: float) -> pd.DataFrame:
    """features ⋈ regimes, one row per (date, pair), only the columns the page draws."""
    r = pd.read_parquet(path_r)
    f = pd.read_parquet(path_f)
    keep_f = ["date", "pair", "vol_20", "mom_20", "corr_20", "vol_ratio"]
    keep_r = ["date", "pair", "regime", "regime_prob", "hmm_entropy", "days_in_regime"]
    if "change_risk_5d" in r.columns:
        keep_r.append("change_risk_5d")
    df = f[keep_f].merge(r[keep_r], on=["date", "pair"], how="inner")
    df = df.dropna(subset=["vol_20", "mom_20"]).sort_values(["pair", "date"])
    df["vol_pct"] = df["vol_20"] * 100.0  # annualised realised vol, in %
    df["mom_pct"] = df["mom_20"] * 100.0  # one-month drift, in %
    return df.reset_index(drop=True)


if not (REGIMES_PATH.exists() and FEATURES_PATH.exists()):
    st.warning("Artifacts missing — run `python pipelines/run_daily.py` first.")
    st.stop()

space_all = load_space(
    str(REGIMES_PATH), _mtime(REGIMES_PATH), str(FEATURES_PATH), _mtime(FEATURES_PATH)
)
regimes_all = space_all[["date", "pair", "regime"]]
pair, as_of, time_machine, episode = ui.scenario_controls(UNI, PAIRS, regimes_all)
ui.mobile_bar(UNI, PAIRS)
space = space_all[space_all["date"] <= as_of]

# --------------------------------------------------------------------------------------
# header + controls
# --------------------------------------------------------------------------------------
st.markdown(
    '<div style="font-size:1.35rem;font-weight:500;margin:0 0 2px 2px">Regime space</div>'
    '<div class="fx-muted" style="margin:0 0 12px 2px">The model\'s feature space, seen from inside. '
    "Each point is one trading day placed by realised volatility, one-month momentum and a third axis; "
    "its colour is the regime the HMM assigned <em>on that day</em> (filtered, causal). "
    "The bright trail is the recent path; the ringed marker is the as-of day.</div>",
    unsafe_allow_html=True,
)
c1, c2, c3, c4 = st.columns([2, 1.2, 1.2, 1.2], vertical_alignment="bottom")
with c1:
    third_label = st.selectbox("Third axis", list(THIRD_AXES), index=0, key="rs_third")
with c2:
    trail_len = st.select_slider("Trail (trading days)", options=[20, 40, 60, 120], value=60)
with c3:
    ghosts = st.toggle(
        "Other pairs' today",
        value=True,
        help="Hollow markers: where the other pairs sit on the same day, in the same feature space.",
    )
with c4:
    lookback = st.select_slider("History drawn", options=["2y", "5y", "10y", "all"], value="all")

zcol, ztitle, _ = THIRD_AXES[third_label]
if zcol not in space.columns:
    zcol, ztitle = "hmm_entropy", "HMM entropy (nats)"

g = space[space["pair"] == pair].dropna(subset=[zcol]).sort_values("date").reset_index(drop=True)
if g.empty:
    st.info("No rows for this pair up to the chosen date.")
    st.stop()
if lookback != "all":
    yrs = int(lookback[:-1])
    g_hist = g[g["date"] >= as_of - pd.DateOffset(years=yrs)]
else:
    g_hist = g
trail = g.tail(trail_len)
today = g.iloc[-1]

# --------------------------------------------------------------------------------------
# state-space portrait
# --------------------------------------------------------------------------------------
SCENE_AXIS = dict(
    backgroundcolor=ui.SURFACE,
    gridcolor=ui.BORDER,
    zerolinecolor=ui.BORDER,
    showbackground=True,
    tickfont=dict(family=ui.FONT_MONO, size=10, color=ui.MUTED),
    title_font=dict(size=11, color=ui.MUTED),
)


def _hover(df: pd.DataFrame) -> list[str]:
    return [
        f"{d:%Y-%m-%d} · {r}<br>vol {v:.1f}% · mom {m:+.1f}% · {ztitle.split(' (')[0]} {z:.2f}"
        for d, r, v, m, z in zip(
            df["date"], df["regime"], df["vol_pct"], df["mom_pct"], df[zcol], strict=True
        )
    ]


def _trail_traces(tr: pd.DataFrame, hover: list[str] | None = None) -> list[go.Scatter3d]:
    """Line + growing markers for the trail, plus the ringed as-of marker (last row of `tr`)."""
    n = len(tr)
    sizes = np.linspace(2.5, 7.0, n) if n > 1 else [7.0]
    last = tr.iloc[-1]
    return [
        go.Scatter3d(
            x=tr["vol_pct"],
            y=tr["mom_pct"],
            z=tr[zcol],
            mode="lines+markers",
            line=dict(color="rgba(231,236,244,0.55)", width=3),
            marker=dict(
                size=sizes,
                color=[ui.REGIME_COLORS[r] for r in tr["regime"]],
                line=dict(color="rgba(11,15,23,0.9)", width=0.5),
            ),
            text=hover if hover is not None else _hover(tr),
            hovertemplate="%{text}<extra>trail</extra>",
            name="recent path",
        ),
        go.Scatter3d(
            x=[last["vol_pct"]],
            y=[last["mom_pct"]],
            z=[last[zcol]],
            mode="markers+text",
            marker=dict(
                size=13,
                color=ui.REGIME_COLORS[last["regime"]],
                symbol="circle",
                line=dict(color=ui.TEXT, width=3),
                opacity=1.0,
            ),
            text=[f"{last['date']:%Y-%m-%d}"],
            textposition="top center",
            textfont=dict(family=ui.FONT_MONO, size=11, color=ui.TEXT),
            hovertemplate="%{text}<extra>as of</extra>",
            name="as of",
        ),
    ]


fig = go.Figure()
# 0: history cloud (dim, coloured by regime) — one trace per regime so the legend can toggle them
for r in REGIME_ORDER:
    h = g_hist[g_hist["regime"] == r]
    fig.add_trace(
        go.Scatter3d(
            x=h["vol_pct"],
            y=h["mom_pct"],
            z=h[zcol],
            mode="markers",
            marker=dict(size=2.2, color=ui.REGIME_COLORS[r], opacity=0.28),
            text=_hover(h),
            hovertemplate="%{text}<extra></extra>",
            name=f"{r} days",
        )
    )
# 4: regime centroids (medians — robust to the crisis tail)
cent = (
    g_hist.groupby("regime")[["vol_pct", "mom_pct", zcol]].median().reindex(REGIME_ORDER).dropna()
)
fig.add_trace(
    go.Scatter3d(
        x=cent["vol_pct"],
        y=cent["mom_pct"],
        z=cent[zcol],
        mode="markers+text",
        marker=dict(
            size=7,
            symbol="diamond",
            color=[ui.REGIME_COLORS[r] for r in cent.index],
            line=dict(color=ui.TEXT, width=1.5),
        ),
        text=[f"{r} centre" for r in cent.index],
        textposition="bottom center",
        textfont=dict(size=10, color=ui.MUTED),
        hovertemplate="%{text}<extra></extra>",
        name="regime centres",
    )
)
# 5: other pairs' as-of position (hollow ghosts)
if ghosts:
    others = (
        space[(space["pair"] != pair)]
        .dropna(subset=[zcol])
        .sort_values("date")
        .groupby("pair")
        .tail(1)
    )
    if len(others):
        fig.add_trace(
            go.Scatter3d(
                x=others["vol_pct"],
                y=others["mom_pct"],
                z=others[zcol],
                mode="markers+text",
                marker=dict(
                    size=9,
                    color="rgba(0,0,0,0)",
                    line=dict(color=[ui.REGIME_COLORS[r] for r in others["regime"]], width=2.5),
                ),
                text=[UNI.display(p) for p in others["pair"]],
                textposition="middle right",
                textfont=dict(size=10, color=ui.MUTED),
                hovertemplate="%{text}<extra>same day</extra>",
                name="other pairs today",
            )
        )
# 6, 7: trail + as-of marker (these two are what the animation replaces)
trail_idx = len(fig.data)
for t in _trail_traces(trail):
    fig.add_trace(t)

# animation: walk the trail through the last ~year. Plotly frames are validated one by one, so
# we keep them cheap: every 2nd trading day (~125 frames) and hover text computed once and sliced.
ANIM_DAYS = min(250, len(g) - trail_len)
frames = []
if ANIM_DAYS > 5:
    hov_all = _hover(g)
    for e in range(len(g) - ANIM_DAYS, len(g) + 1, 2):
        lo = max(0, e - trail_len)
        tr = g.iloc[lo:e]
        frames.append(
            go.Frame(
                data=_trail_traces(tr, hover=hov_all[lo:e]),
                traces=[trail_idx, trail_idx + 1],
                name=f"{tr.iloc[-1]['date']:%Y-%m-%d}",
            )
        )
    if frames[-1].name != f"{today['date']:%Y-%m-%d}":  # always end exactly on the as-of day
        frames.append(
            go.Frame(
                data=_trail_traces(trail, hover=hov_all[-len(trail) :]),
                traces=[trail_idx, trail_idx + 1],
                name=f"{today['date']:%Y-%m-%d}",
            )
        )
    fig.frames = frames

xr = np.log10([max(g_hist["vol_pct"].min() * 0.9, 0.5), g_hist["vol_pct"].max() * 1.1])
fig.update_layout(
    template=ui.PLOTLY_TEMPLATE,
    height=600,
    margin=dict(l=0, r=0, t=30, b=90),
    scene=dict(
        xaxis=dict(SCENE_AXIS, title="realised vol, ann. % (log)", type="log", range=list(xr)),
        yaxis=dict(SCENE_AXIS, title="1-month momentum %"),
        zaxis=dict(SCENE_AXIS, title=ztitle),
        bgcolor=ui.BG,
        camera=dict(eye=dict(x=1.25, y=-1.4, z=0.7)),
        aspectmode="cube",
    ),
    legend=dict(orientation="h", x=0.0, y=1.02, yanchor="bottom", font=dict(size=11)),
    hoverlabel=dict(font=dict(family=ui.FONT_MONO, size=11)),
    updatemenus=(
        [
            dict(
                type="buttons",
                showactive=False,
                x=0.0,
                y=-0.02,
                xanchor="left",
                yanchor="top",
                bgcolor=ui.SURFACE,
                bordercolor=ui.BORDER,
                font=dict(color=ui.TEXT, size=11),
                buttons=[
                    dict(
                        label="▶ play the last year",
                        method="animate",
                        args=[
                            None,
                            dict(
                                frame=dict(duration=45, redraw=True),
                                fromcurrent=True,
                                transition=dict(duration=0),
                            ),
                        ],
                    ),
                    dict(
                        label="❚❚ pause",
                        method="animate",
                        args=[[None], dict(frame=dict(duration=0, redraw=False), mode="immediate")],
                    ),
                ],
            )
        ]
        if frames
        else []
    ),
    sliders=(
        [
            dict(
                active=len(frames) - 1,
                x=0.28,
                y=-0.02,
                yanchor="top",
                len=0.7,
                pad=dict(t=0, b=0),
                bgcolor=ui.BORDER,
                bordercolor=ui.BORDER,
                activebgcolor=ui.TEXT,
                font=dict(color=ui.MUTED, size=9),
                currentvalue=dict(
                    visible=True,
                    prefix="trail ends ",
                    font=dict(color=ui.MUTED, size=10),
                    xanchor="left",
                ),
                steps=[
                    dict(
                        method="animate",
                        label=f.name[:7],
                        args=[
                            [f.name],
                            dict(
                                mode="immediate",
                                frame=dict(duration=0, redraw=True),
                                transition=dict(duration=0),
                            ),
                        ],
                    )
                    for f in frames
                ],
            )
        ]
        if frames
        else []
    ),
)
st.markdown(
    f'<div style="font-weight:500;margin:6px 0 4px 2px">State-space portrait — {UNI.display(pair)}'
    + (f" · as of {as_of:%Y-%m-%d}" if time_machine else "")
    + '</div><div class="fx-muted" style="font-size:0.8rem;margin:0 0 6px 2px">Drag to orbit · scroll to zoom · click a legend entry to hide a regime · ▶ replays the trail day by day. Points sit where the model saw them; the four clouds are the regimes.</div>',
    unsafe_allow_html=True,
)
st.plotly_chart(fig, width="stretch", config={"displayModeBar": False, "scrollZoom": True})

# --------------------------------------------------------------------------------------
# geometry readout: how far is today from each regime's centre, in history's own units
# --------------------------------------------------------------------------------------
cols = ["vol_pct", "mom_pct", zcol]
zs = g_hist[cols].copy()
zs["vol_pct"] = np.log10(zs["vol_pct"].clip(lower=0.5))
mu, sd = zs.mean(), zs.std(ddof=0).replace(0, 1)
tp = pd.Series(
    {
        "vol_pct": np.log10(max(today["vol_pct"], 0.5)),
        "mom_pct": today["mom_pct"],
        zcol: today[zcol],
    }
)
zt = (tp - mu) / sd
dist = {}
for r in REGIME_ORDER:
    hr = zs[g_hist["regime"] == r]
    if len(hr):
        c = ((hr - mu) / sd).median()
        dist[r] = float(np.sqrt(((zt - c) ** 2).sum()))
nearest = min(dist, key=dist.get) if dist else today["regime"]
tiles = [
    ui.kpi(
        "as-of regime",
        ui.regime_pill(str(today["regime"])),
        f"prob {today['regime_prob']:.0%} · day {int(today['days_in_regime'])} of the run",
    ),
    ui.kpi(
        "realised vol",
        f"{today['vol_pct']:.1f}%",
        f"pct rank {100 * (g_hist['vol_pct'] < today['vol_pct']).mean():.0f} of history",
    ),
    ui.kpi("1-month momentum", f"{today['mom_pct']:+.1f}%", "drift, not a forecast"),
    ui.kpi(
        "nearest centre",
        nearest,
        " · ".join(f"{r} {d:.1f}σ" for r, d in dist.items()),
        ui.REGIME_COLORS.get(nearest, ui.TEXT),
    ),
]
ui.kpi_strip(tiles)
st.markdown(
    '<div class="fx-muted" style="font-size:0.78rem;margin:-4px 0 14px 2px">Distances are z-scored Euclidean to each regime\'s median in the three drawn axes — a geometric aid to reading the picture. The regime label and its probability come from the HMM (filtered), which also uses persistence; the two can disagree, and when they do it is usually because the model is waiting for confirmation.</div>',
    unsafe_allow_html=True,
)


# --------------------------------------------------------------------------------------
# regime landscape: density terrain over (vol, momentum), coloured by the dominant regime
# --------------------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def landscape(
    vol_pct: np.ndarray, mom_pct: np.ndarray, regime_idx: np.ndarray, nx: int = 48, ny: int = 40
):
    """Smoothed 2-D histogram of history + the most frequent regime per cell (all plain numpy)."""
    lx = np.log10(np.clip(vol_pct, 0.5, None))
    xe = np.linspace(lx.min() - 0.02, lx.max() + 0.02, nx + 1)
    ye = np.linspace(mom_pct.min() - 0.2, mom_pct.max() + 0.2, ny + 1)
    k = np.array([1, 4, 6, 4, 1], dtype=float)
    k = np.outer(k, k)
    k /= k.sum()

    def smooth(h: np.ndarray) -> np.ndarray:
        # 5x5 binomial blur with edge padding — a poor man's gaussian, no scipy needed
        p = np.pad(h, 2, mode="edge")
        out = np.zeros_like(h)
        for i in range(5):
            for j in range(5):
                out += k[i, j] * p[i : i + h.shape[0], j : j + h.shape[1]]
        return out

    per = []
    for i in range(len(REGIME_ORDER)):
        m = regime_idx == i
        h, _, _ = np.histogram2d(lx[m], mom_pct[m], bins=[xe, ye])
        per.append(smooth(h))
    per = np.stack(per)  # regime, x, y
    total = per.sum(axis=0)
    dom = per.argmax(axis=0).astype(float)
    # Empty cells (nobody lives here) are cut out of the terrain (NaN height). Their colour index
    # is inherited from the nearest populated cell: Plotly interpolates the colour index across a
    # face, so a jump to a separate "empty" category would paint rainbow seams along every rim.
    empty = total < 0.35
    if empty.any() and (~empty).any():
        from scipy import ndimage  # already installed with scikit-learn / hmmlearn

        _, (ix, iy) = ndimage.distance_transform_edt(empty, return_indices=True)
        dom = dom[ix, iy]
    z = np.log1p(total)
    z[empty] = np.nan
    return xe, ye, z.T, dom.T  # plotly surface wants z[y, x]


xe, ye, Z, DOM = landscape(
    g_hist["vol_pct"].to_numpy(),
    g_hist["mom_pct"].to_numpy(),
    g_hist["regime"].map(REGIME_IDX).to_numpy(),
)
xc = 10 ** ((xe[:-1] + xe[1:]) / 2)
yc = (ye[:-1] + ye[1:]) / 2


def _z_on_surface(v: pd.Series, m: pd.Series) -> np.ndarray:
    ix = np.clip(np.searchsorted(xe, np.log10(np.clip(v, 0.5, None))) - 1, 0, len(xc) - 1)
    iy = np.clip(np.searchsorted(ye, m) - 1, 0, len(yc) - 1)
    return np.nan_to_num(Z[iy, ix], nan=0.0) + 0.12


cs = [  # four flat bands, in vol order (calm→crisis) so neighbouring regimes are neighbouring colours
    [0.0, ui.REGIME_COLORS["calm"]],
    [0.25, ui.REGIME_COLORS["calm"]],
    [0.25, ui.REGIME_COLORS["trend"]],
    [0.5, ui.REGIME_COLORS["trend"]],
    [0.5, ui.REGIME_COLORS["chop"]],
    [0.75, ui.REGIME_COLORS["chop"]],
    [0.75, ui.REGIME_COLORS["crisis"]],
    [1.0, ui.REGIME_COLORS["crisis"]],
]
land = go.Figure()
land.add_trace(
    go.Surface(
        x=xc,
        y=yc,
        z=Z,
        surfacecolor=DOM,
        colorscale=cs,
        cmin=-0.5,
        cmax=3.5,
        showscale=False,
        opacity=0.92,
        contours=dict(
            z=dict(
                show=True,
                usecolormap=False,
                color="rgba(11,15,23,0.35)",
                width=1,
                start=0.2,
                end=float(np.nanmax(Z)),
                size=max(float(np.nanmax(Z)) / 8, 0.1),
            )
        ),
        lighting=dict(ambient=0.55, diffuse=0.6, specular=0.15, roughness=0.8),
        hovertemplate="vol %{x:.1f}% · mom %{y:+.1f}%<br>height %{z:.2f} (log days)<extra></extra>",
        name="history density",
    )
)
land.add_trace(
    go.Scatter3d(
        x=trail["vol_pct"],
        y=trail["mom_pct"],
        z=_z_on_surface(trail["vol_pct"], trail["mom_pct"]),
        mode="lines+markers",
        line=dict(color="rgba(231,236,244,0.8)", width=4),
        marker=dict(
            size=np.linspace(2.5, 6.5, len(trail)),
            color=[ui.REGIME_COLORS[r] for r in trail["regime"]],
            line=dict(color=ui.BG, width=0.5),
        ),
        text=_hover(trail),
        hovertemplate="%{text}<extra>trail</extra>",
        name=f"last {len(trail)} days",
    )
)
land.add_trace(
    go.Scatter3d(
        x=[today["vol_pct"]],
        y=[today["mom_pct"]],
        z=_z_on_surface(pd.Series([today["vol_pct"]]), pd.Series([today["mom_pct"]])) + 0.05,
        mode="markers+text",
        marker=dict(
            size=12, color=ui.REGIME_COLORS[today["regime"]], line=dict(color=ui.TEXT, width=3)
        ),
        text=[f"{today['date']:%Y-%m-%d}"],
        textposition="top center",
        textfont=dict(family=ui.FONT_MONO, size=11, color=ui.TEXT),
        hovertemplate="%{text}<extra>as of</extra>",
        name="as of",
    )
)
land.update_layout(
    template=ui.PLOTLY_TEMPLATE,
    height=540,
    margin=dict(l=0, r=0, t=30, b=0),
    scene=dict(
        xaxis=dict(SCENE_AXIS, title="realised vol, ann. % (log)", type="log"),
        yaxis=dict(SCENE_AXIS, title="1-month momentum %"),
        zaxis=dict(SCENE_AXIS, title="how much history lives here (log days)"),
        bgcolor=ui.BG,
        camera=dict(eye=dict(x=1.0, y=-1.2, z=0.65)),
        aspectratio=dict(x=1.2, y=1.0, z=0.45),
    ),
    legend=dict(orientation="h", x=0.0, y=1.02, yanchor="bottom", font=dict(size=11)),
    showlegend=True,
)
legend = " ".join(ui.regime_pill(r) for r in REGIME_ORDER)
st.markdown(
    f'<div style="display:flex;justify-content:space-between;align-items:center;margin:14px 0 4px 2px"><span style="font-weight:500">Regime landscape — {UNI.display(pair)}</span><span>{legend}</span></div>'
    '<div class="fx-muted" style="font-size:0.8rem;margin:0 0 6px 2px">Height = how many days of history sit at that (vol, momentum); colour = the regime the HMM most often called there. Calm is the big hill at low vol; crisis is the thin high-vol ridge. The trail shows the market walking over the terrain to today.</div>',
    unsafe_allow_html=True,
)
st.plotly_chart(land, width="stretch", config={"displayModeBar": False, "scrollZoom": True})

ui.card(
    '<div class="fx-muted" style="font-size:0.82rem">'
    "<b>How to read it, in one breath.</b> An HMM is a clustering with memory: each regime is a cloud in "
    "feature space, and the transition matrix makes the model reluctant to hop between clouds. The portrait "
    "shows the clouds; the landscape shows how densely each part of the space has been visited and which label "
    "won there; the trail shows the path the market took to today. Position is descriptive — the axes are "
    "computed from data up to each day (rule 1) — and nothing on this page is a price forecast."
    "</div>",
    title="What this page is (and is not)",
)
ui.footer(
    DISCLAIMER,
    "· 3D views are WebGL (Plotly); the pipeline computed every number, the app only draws.",
)
