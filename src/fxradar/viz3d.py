"""viz3d — two mathematically honest 3-D pictures of what the pipeline already computes.

DISPLAY LAYER ONLY. Nothing here changes a feature, a model, a label or an artifact.

A) The regime tetrahedron. The HMM's four FILTERED probabilities sum to one, so every day is a
   point in a 3-simplex — a tetrahedron whose corners are the four regimes. `simplex_coords`
   is the linear map `probs @ V`; the centroid (uniform 1/4 each) is the origin.
B) The market landscape. A PCA(3) embedding of the day-level feature vectors, FIT ON TRAIN ROWS
   ONLY (same discipline as every model), then applied to the full history; days coloured by
   regime, the last 60 days as a trail, today ringed. The fitted embedding is persisted with
   joblib next to the frozen models (`models/landscape_<pair>.joblib`) by an OFFLINE step
   (`python -m fxradar.viz3d --fit`), so the app only loads it (rule 8: pipeline writes, app reads).

The four probabilities are not stored in regimes.parquet (only the winner and its probability),
so `probability_frame` replays the frozen bundle's forward filter — the same `filtered_probs`
the pipeline used, causal by construction (only rows <= t feed row t). Never the smoother.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler

from fxradar import config
from fxradar import hmm_model as hm
from fxradar.features import BASE_FEATURES

# --------------------------------------------------------------------------------------
# the simplex
# --------------------------------------------------------------------------------------
REGIME_ORDER: list[str] = ["calm", "trend", "chop", "crisis"]  # the frozen naming order
VERTICES = np.array(
    [[1, 1, 1], [1, -1, -1], [-1, 1, -1], [-1, -1, 1]], dtype=float
)  # rows = REGIME_ORDER
EDGES = [(0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)]
REGIME_COLORS = {"calm": "#34D399", "trend": "#60A5FA", "chop": "#FBBF24", "crisis": "#F87171"}
TEXT, MUTED, BORDER = "#E7ECF4", "#8A94A6", "#232D3F"
PROB_COLUMNS = [f"p_{r}" for r in REGIME_ORDER]
TRAIL_DAYS = 60
LANDSCAPE_FEATURES: list[str] = list(
    BASE_FEATURES
)  # 8 causal features (the HMM uses only 3 — PCA(3) of 3 would be a mere rotation)


def simplex_coords(probs: np.ndarray, order: list[str] = REGIME_ORDER) -> np.ndarray:
    """Map rows of 4 regime probabilities to points in the tetrahedron: exactly `probs @ V`.

    `order` is the caller's statement of how its columns are ordered; it must equal the frozen
    naming order the vertex rows follow (never inferred). Rows must be non-negative and sum to
    one within 1e-9. The uniform row maps to the origin (the centroid).
    """
    if list(order) != REGIME_ORDER:
        raise ValueError(f"probability columns must be ordered {REGIME_ORDER}, got {list(order)}")
    p = np.asarray(probs, dtype=float)
    if p.ndim != 2 or p.shape[1] != 4:
        raise ValueError(f"expected an array of shape (T, 4), got {p.shape}")
    if not np.isfinite(p).all() or (p < 0).any():
        raise ValueError("probabilities must be finite and non-negative")
    if not np.allclose(p.sum(axis=1), 1.0, atol=1e-9, rtol=0):
        raise ValueError("every probability row must sum to 1 (within 1e-9)")
    return p @ VERTICES


# --------------------------------------------------------------------------------------
# data: filtered probabilities replayed from the frozen bundle (causal), joined to regimes
# --------------------------------------------------------------------------------------
def filtered_probability_table(feats_pair: pd.DataFrame, bundle: hm.HMMBundle) -> pd.DataFrame:
    """date + p_calm..p_crisis for one pair: the forward filter of the FROZEN bundle on the same
    scaled features the pipeline scores — no refit, no smoother. Columns follow REGIME_ORDER."""
    g = feats_pair.sort_values("date").reset_index(drop=True)
    X = bundle.scaler.transform(g[bundle.features].to_numpy())
    probs = hm.filtered_probs(bundle.model, X)  # P(state_t | x_1..x_t)
    name_to_state = {name: state for state, name in bundle.mapping.items()}
    if sorted(name_to_state) != sorted(REGIME_ORDER):
        raise ValueError(f"bundle mapping {bundle.mapping} is not the four frozen regime names")
    ordered = probs[:, [name_to_state[r] for r in REGIME_ORDER]]
    out = pd.DataFrame(ordered, columns=PROB_COLUMNS)
    out.insert(0, "date", g["date"].to_numpy())
    return out


def probability_frame(
    pair: str,
    features: pd.DataFrame,
    regimes: pd.DataFrame,
    bundle: hm.HMMBundle,
) -> pd.DataFrame:
    """One row per day: date, p_* (filtered), regime, regime_prob, siren (anomaly_pct)."""
    f = features[features["pair"] == pair]
    r = regimes[regimes["pair"] == pair][["date", "regime", "regime_prob", "anomaly_pct"]]
    table = filtered_probability_table(f, bundle).merge(r, on="date", how="inner")
    return table.sort_values("date").reset_index(drop=True)


def load_inputs(
    data_dir: Path = config.DATA_DIR, models_dir: Path = config.MODELS_DIR
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, hm.HMMBundle]]:
    """I/O at the edge: features, regimes and the frozen HMM bundles of one universe."""
    features = pd.read_parquet(data_dir / "features.parquet")
    regimes = pd.read_parquet(data_dir / "regimes.parquet")
    pairs = sorted(regimes["pair"].unique())
    bundles = hm.load_bundles(pairs=pairs, models_dir=models_dir)
    return features, regimes, bundles


# --------------------------------------------------------------------------------------
# A) tetrahedron figure
# --------------------------------------------------------------------------------------
def _hover_probs(frame: pd.DataFrame) -> list[str]:
    return [
        f"{d:%Y-%m-%d}<br>calm {a:.2f} · trend {b:.2f} · chop {c:.2f} · crisis {e:.2f}"
        f"<br>siren {s:.0f}"
        for d, a, b, c, e, s in zip(
            frame["date"],
            frame["p_calm"],
            frame["p_trend"],
            frame["p_chop"],
            frame["p_crisis"],
            frame["anomaly_pct"].fillna(0.0),
            strict=True,
        )
    ]


def _bare_scene(**extra) -> dict:
    """No axes, ticks, grids or planes: simplex coordinates carry no units."""
    ax = dict(
        visible=False,
        showbackground=False,
        showgrid=False,
        zeroline=False,
        showticklabels=False,
        title="",
    )
    return dict(xaxis=ax, yaxis=ax, zaxis=ax, aspectmode="data", **extra)


def tetrahedron_figure(
    frame: pd.DataFrame,
    pair: str,
    color_by: str = "time",
    template: str | None = None,
) -> go.Figure:
    """The pair's daily path through the probability simplex (filtered probabilities only).

    `color_by="time"` colours the path by day index; `"siren"` by anomaly percentile with a
    colorbar. Today is a larger marker with a ring. Edges are thin neutral lines; the four
    vertices are labelled with the regime names in the dashboard palette.
    """
    if color_by not in ("time", "siren"):
        raise ValueError("color_by must be 'time' or 'siren'")
    fr = frame.sort_values("date").reset_index(drop=True)
    xyz = simplex_coords(fr[PROB_COLUMNS].to_numpy(), REGIME_ORDER)
    fig = go.Figure()
    for i, j in EDGES:  # 6 edges
        fig.add_trace(
            go.Scatter3d(
                x=[VERTICES[i, 0], VERTICES[j, 0]],
                y=[VERTICES[i, 1], VERTICES[j, 1]],
                z=[VERTICES[i, 2], VERTICES[j, 2]],
                mode="lines",
                line=dict(color=BORDER, width=2),
                hoverinfo="skip",
                showlegend=False,
            )
        )
    for k, name in enumerate(REGIME_ORDER):  # 4 vertices
        fig.add_trace(
            go.Scatter3d(
                x=[VERTICES[k, 0]],
                y=[VERTICES[k, 1]],
                z=[VERTICES[k, 2]],
                mode="markers+text",
                marker=dict(size=7, color=REGIME_COLORS[name]),
                text=[name.upper()],
                textposition="top center",
                textfont=dict(color=REGIME_COLORS[name], size=12),
                hovertemplate=f"{name}: probability 1 here<extra></extra>",
                showlegend=False,
            )
        )
    if color_by == "time":
        marker = dict(
            size=2.5,
            color=np.arange(len(fr)),
            colorscale=[[0, "#3B4A63"], [1, TEXT]],
            showscale=False,
        )
        line = dict(color=np.arange(len(fr)), colorscale=[[0, "#3B4A63"], [1, TEXT]], width=2)
    else:
        siren = fr["anomaly_pct"].fillna(0.0).to_numpy()
        scale = [[0, "#3B4A63"], [0.9, REGIME_COLORS["chop"]], [1, REGIME_COLORS["crisis"]]]
        marker = dict(
            size=2.5,
            color=siren,
            cmin=0,
            cmax=100,
            colorscale=scale,
            colorbar=dict(title="siren pct", thickness=10, len=0.5, x=1.0),
        )
        line = dict(color=siren, cmin=0, cmax=100, colorscale=scale, width=2)
    fig.add_trace(
        go.Scatter3d(
            x=xyz[:, 0],
            y=xyz[:, 1],
            z=xyz[:, 2],
            mode="lines+markers",
            marker=marker,
            line=line,
            text=_hover_probs(fr),
            hovertemplate="%{text}<extra></extra>",
            name="daily path (filtered)",
            showlegend=False,
        )
    )
    today = fr.iloc[-1]
    tx, ty, tz = xyz[-1]
    fig.add_trace(  # today: larger marker with a ring
        go.Scatter3d(
            x=[tx, tx],
            y=[ty, ty],
            z=[tz, tz],
            mode="markers",
            marker=dict(
                size=[8, 14],
                color=[REGIME_COLORS[str(today["regime"])], "rgba(0,0,0,0)"],
                symbol=["circle", "circle-open"],
                line=dict(color=TEXT, width=2),
            ),
            text=[_hover_probs(fr.tail(1))[0]] * 2,
            hovertemplate="today · %{text}<extra></extra>",
            showlegend=False,
        )
    )
    fig.update_layout(
        template=template,
        title=dict(text=f"{pair} — the last {len(fr):,} days in the probability simplex", x=0.02),
        scene=_bare_scene(camera=dict(eye=dict(x=1.6, y=1.3, z=1.0))),
        margin=dict(l=0, r=0, t=40, b=0),
        height=520,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig


# --------------------------------------------------------------------------------------
# B) landscape embedding — fit on train rows only, persisted, loaded by the app
# --------------------------------------------------------------------------------------
@dataclass
class LandscapeEmbedding:
    """A frozen (scaler → PCA) map from day-level features to 3-D. `train_end` and `n_fit_rows`
    make the train-only fit auditable; `explained` is the PCA variance ratio."""

    pair: str
    scaler: StandardScaler
    reducer: object  # sklearn PCA (or umap.UMAP when explicitly requested and importable)
    train_end: str
    n_fit_rows: int
    method: str = "pca"
    features: list[str] = field(default_factory=lambda: list(LANDSCAPE_FEATURES))
    explained: list[float] = field(default_factory=list)

    def transform(self, feats: pd.DataFrame) -> np.ndarray:
        """Embed rows (any dates — the map is frozen); rows with a missing feature come out NaN."""
        X = feats[self.features].to_numpy(dtype=float)
        out = np.full((len(X), 3), np.nan)
        ok = np.isfinite(X).all(axis=1)
        if ok.any():
            out[ok] = self.reducer.transform(self.scaler.transform(X[ok]))
        return out


def fit_landscape_embedding(
    features: pd.DataFrame,
    train_end: str = config.TRAIN_END,
    method: str = "pca",
    feature_cols: list[str] | None = None,
    pair: str = "",
) -> LandscapeEmbedding:
    """Fit scaler + PCA(3, random_state=42) on rows with date <= train_end ONLY, for one pair.

    `features` is one pair's rows of features.parquet. Rows with a missing feature are excluded
    from the fit. `method="umap"` is accepted only if umap-learn is already importable (it is not
    a dependency of this project); PCA is the default and the frozen choice.
    """
    cols = list(feature_cols or LANDSCAPE_FEATURES)
    df = features.sort_values("date")
    train = df[hm.train_mask(df["date"], train_end)]  # <-- the train-only slice
    X_train = train[cols].to_numpy(dtype=float)
    X_train = X_train[np.isfinite(X_train).all(axis=1)]
    if len(X_train) < 10:
        raise ValueError(f"not enough train rows to fit the landscape ({len(X_train)})")
    scaler = StandardScaler().fit(X_train)
    if method == "pca":
        reducer = PCA(n_components=3, random_state=42).fit(scaler.transform(X_train))
        explained = [float(v) for v in reducer.explained_variance_ratio_]
    elif method == "umap":
        try:
            import umap  # optional; never added to requirements
        except ImportError as exc:  # pragma: no cover - depends on the environment
            raise ValueError("method='umap' needs umap-learn, which is not installed") from exc
        reducer = umap.UMAP(n_components=3, random_state=42).fit(scaler.transform(X_train))
        explained = []
    else:
        raise ValueError("method must be 'pca' or 'umap'")
    return LandscapeEmbedding(
        pair=pair,
        scaler=scaler,
        reducer=reducer,
        train_end=str(pd.Timestamp(train_end).date()),
        n_fit_rows=int(len(X_train)),
        method=method,
        features=cols,
        explained=explained,
    )


def embedding_path(pair: str, models_dir: Path = config.MODELS_DIR, method: str = "pca") -> Path:
    return models_dir / f"landscape_{pair}_{method}.joblib"


def save_embedding(emb: LandscapeEmbedding, models_dir: Path = config.MODELS_DIR) -> Path:
    """Persist as a dict of library objects (never our own class), like the HMM bundles."""
    path = embedding_path(emb.pair, models_dir, emb.method)
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {
            "pair": emb.pair,
            "scaler": emb.scaler,
            "reducer": emb.reducer,
            "train_end": emb.train_end,
            "n_fit_rows": emb.n_fit_rows,
            "method": emb.method,
            "features": list(emb.features),
            "explained": list(emb.explained),
        },
        path,
    )
    return path


def load_embedding(
    pair: str, models_dir: Path = config.MODELS_DIR, method: str = "pca"
) -> LandscapeEmbedding:
    return LandscapeEmbedding(**joblib.load(embedding_path(pair, models_dir, method)))


def landscape_frame(pair: str, features: pd.DataFrame, regimes: pd.DataFrame) -> pd.DataFrame:
    """One pair's features ⋈ regimes (date, features..., regime, anomaly_pct), oldest first."""
    f = features[features["pair"] == pair]
    r = regimes[regimes["pair"] == pair][["date", "regime", "anomaly_pct"]]
    return f.merge(r, on="date", how="inner").sort_values("date").reset_index(drop=True)


def landscape_figure(
    frame: pd.DataFrame,
    embedding: LandscapeEmbedding,
    pair: str,
    trail_days: int = TRAIL_DAYS,
    template: str | None = None,
) -> go.Figure:
    """All days as points coloured by regime, the last `trail_days` as a brightening trail, today
    as a larger ringed marker. Hover: date, regime, siren. Coordinates come from the frozen
    (train-only) embedding, so two calls with the same inputs give identical points."""
    fr = frame.sort_values("date").reset_index(drop=True)
    xyz = embedding.transform(fr)
    ok = np.isfinite(xyz).all(axis=1)
    fr, xyz = fr[ok].reset_index(drop=True), xyz[ok]
    hover = [
        f"{d:%Y-%m-%d}<br>{g} · siren {s:.0f}"
        for d, g, s in zip(fr["date"], fr["regime"], fr["anomaly_pct"].fillna(0.0), strict=True)
    ]
    fig = go.Figure()
    for name in REGIME_ORDER:
        m = (fr["regime"] == name).to_numpy()
        if not m.any():
            continue
        fig.add_trace(
            go.Scatter3d(
                x=xyz[m, 0],
                y=xyz[m, 1],
                z=xyz[m, 2],
                mode="markers",
                marker=dict(size=2.2, color=REGIME_COLORS[name], opacity=0.55),
                text=[h for h, keep in zip(hover, m, strict=True) if keep],
                hovertemplate="%{text}<extra></extra>",
                name=name,
            )
        )
    n = min(trail_days, len(fr))
    idx = np.arange(n)
    fig.add_trace(  # trail: colour brightens toward today (Scatter3d has no per-point opacity)
        go.Scatter3d(
            x=xyz[-n:, 0],
            y=xyz[-n:, 1],
            z=xyz[-n:, 2],
            mode="lines+markers",
            line=dict(
                color=idx,
                colorscale=[[0, "rgba(231,236,244,0.15)"], [1, "rgba(231,236,244,1)"]],
                width=4,
            ),
            marker=dict(
                size=3,
                color=idx,
                colorscale=[[0, "rgba(231,236,244,0.2)"], [1, "rgba(231,236,244,1)"]],
            ),
            text=hover[-n:],
            hovertemplate="%{text}<extra></extra>",
            name=f"last {n} days",
        )
    )
    tx, ty, tz = xyz[-1]
    fig.add_trace(
        go.Scatter3d(
            x=[tx, tx],
            y=[ty, ty],
            z=[tz, tz],
            mode="markers",
            marker=dict(
                size=[9, 15],
                color=[REGIME_COLORS[str(fr.iloc[-1]["regime"])], "rgba(0,0,0,0)"],
                symbol=["circle", "circle-open"],
                line=dict(color=TEXT, width=2),
            ),
            text=[hover[-1]] * 2,
            hovertemplate="today · %{text}<extra></extra>",
            name="today",
        )
    )
    ev = embedding.explained
    labels = [f"PC{i + 1}" + (f" ({ev[i]:.0%})" if i < len(ev) else "") for i in range(3)]
    ax = dict(showbackground=False, gridcolor=BORDER, zeroline=False, color=MUTED)
    fig.update_layout(
        template=template,
        title=dict(
            text=f"{pair} — {len(fr):,} days embedded (PCA fit on train ≤ {embedding.train_end}, "
            f"{embedding.n_fit_rows:,} rows)",
            x=0.02,
        ),
        scene=dict(
            xaxis=dict(title=labels[0], **ax),
            yaxis=dict(title=labels[1], **ax),
            zaxis=dict(title=labels[2], **ax),
            aspectmode="cube",
            camera=dict(eye=dict(x=1.5, y=1.4, z=0.9)),
        ),
        legend=dict(orientation="h", y=-0.02, x=0.0),
        margin=dict(l=0, r=0, t=40, b=0),
        height=560,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig


# --------------------------------------------------------------------------------------
# offline step: fit + persist the embeddings for the current universe
# --------------------------------------------------------------------------------------
def fit_all(
    data_dir: Path = config.DATA_DIR,
    models_dir: Path = config.MODELS_DIR,
    train_end: str = config.TRAIN_END,
    method: str = "pca",
) -> dict[str, Path]:
    """Fit one landscape embedding per pair (train rows only) and save them next to the models."""
    features = pd.read_parquet(data_dir / "features.parquet")
    out: dict[str, Path] = {}
    for pair in sorted(features["pair"].unique()):
        emb = fit_landscape_embedding(
            features[features["pair"] == pair], train_end=train_end, method=method, pair=pair
        )
        out[pair] = save_embedding(emb, models_dir)
        print(
            f"{pair}: fit on {emb.n_fit_rows} rows <= {emb.train_end} "
            f"(explained {', '.join(f'{v:.0%}' for v in emb.explained)}) -> {out[pair]}"
        )
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="viz3d offline step (display layer only)")
    ap.add_argument("--fit", action="store_true", help="fit + save the landscape embeddings")
    ap.add_argument("--method", default="pca", choices=["pca", "umap"])
    a = ap.parse_args()
    if a.fit:
        fit_all(method=a.method)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
