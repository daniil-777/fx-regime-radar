"""Anomaly siren: a tiny MLP autoencoder whose reconstruction error flags unusual market days.

Trained ONLY on train-period days the HMM called calm with confidence (regime_prob > 0.7), pooled
across pairs and WITHOUT pair one-hots: the siren is pair-agnostic on purpose — "normal" is a
shared shape of the nine continuous features, and giving it pair identity would let it memorise
which pair it is looking at instead of what normal looks like. The 8-3-8 bottleneck forces the
network to compress normal days; a day it cannot rebuild is, by construction, unlike anything it
saw in calm training data. It DETECTS weirdness; it predicts nothing.
"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.neighbors import NearestNeighbors
from sklearn.neural_network import MLPRegressor
from sklearn.preprocessing import StandardScaler

from fxradar import config
from fxradar import hmm_model as hm

log = logging.getLogger(__name__)

SIREN_VERSION = "1.2.0"
SIREN_FEATURES: list[str] = [
    "vol_20",
    "vol_60",
    "vol_ratio",
    "mom_20",
    "rng_hl",
    "corr_20",
    "ret_5d_abs",
    "hmm_entropy",
    "ret_1d",
]
HIDDEN = (8, 3, 8)
CALM_PROB = 0.7
NN_EXCLUDE_DAYS = 10
KNOWN_EVENTS = {k: list(v) for k, v in config.UNIVERSE.known_events.items()}  # per universe


# --------------------------------------------------------------------------------------
# training set + fit
# --------------------------------------------------------------------------------------
def calm_train_mask(
    df: pd.DataFrame, train_end: str = config.TRAIN_END, calm_prob: float = CALM_PROB
) -> pd.Series:
    """Rows the siren may learn from: train period AND regime == calm AND regime_prob > calm_prob."""
    return (
        (df["date"] <= pd.Timestamp(train_end))
        & (df["regime"] == "calm")
        & (df["regime_prob"] > calm_prob)
    )


def joined(features: pd.DataFrame, regimes: pd.DataFrame) -> pd.DataFrame:
    cols = ["date", "pair", "regime", "regime_prob"]
    return (
        features.merge(regimes[cols], on=["date", "pair"], how="inner")
        .sort_values(["pair", "date"])
        .reset_index(drop=True)
    )


def fit_siren(df: pd.DataFrame, train_end: str = config.TRAIN_END, random_state: int = 42) -> dict:
    """Fit scaler + autoencoder on calm train days. Returns a plain-dict bundle (joblib-safe)."""
    mask = calm_train_mask(df, train_end)
    x_raw = df.loc[mask, SIREN_FEATURES].to_numpy()
    if len(x_raw) < 200:
        raise ValueError(f"only {len(x_raw)} calm training days")
    scaler = StandardScaler().fit(x_raw)
    x = scaler.transform(x_raw)
    ae = MLPRegressor(
        hidden_layer_sizes=HIDDEN, max_iter=3000, early_stopping=True, random_state=random_state
    )
    ae.fit(x, x)
    train_err = ((ae.predict(x) - x) ** 2).mean(axis=1)
    return {
        "version": SIREN_VERSION,
        "features": list(SIREN_FEATURES),
        "scaler": scaler,
        "model": ae,
        "train_scores": np.sort(train_err),  # reference distribution for percentiles
        "train_end": train_end,
        "n_train": int(len(x_raw)),
        "train_dates": (
            str(df.loc[mask, "date"].min().date()),
            str(df.loc[mask, "date"].max().date()),
        ),
        "n_iter": int(ae.n_iter_),
    }


# --------------------------------------------------------------------------------------
# scoring
# --------------------------------------------------------------------------------------
def reconstruction_errors(bundle: dict, df: pd.DataFrame) -> np.ndarray:
    """Per-feature squared reconstruction error in scaled space -> (n, 9)."""
    x = bundle["scaler"].transform(df[SIREN_FEATURES].to_numpy())
    return (bundle["model"].predict(x) - x) ** 2


def percentile_of(scores: np.ndarray, reference: np.ndarray) -> np.ndarray:
    """Percentile (0-100) of each score within the sorted reference distribution."""
    return np.searchsorted(reference, scores, side="right") / len(reference) * 100.0


def nearest_neighbors(
    bundle: dict,
    df: pd.DataFrame,
    train_end: str | None = None,
    exclude_days: int = NN_EXCLUDE_DAYS,
) -> pd.DataFrame:
    """For every row: the train-period date of the SAME pair with the closest (scaled) feature vector,
    excluding +/- `exclude_days` calendar days around the row itself. Returns date, pair, nn_date, nn_dist.
    """
    train_end = pd.Timestamp(train_end or bundle["train_end"])
    out = []
    for pair, g in df.groupby("pair", sort=False):
        g = g.sort_values("date")
        x_all = bundle["scaler"].transform(g[SIREN_FEATURES].to_numpy())
        ref = g["date"] <= train_end
        x_ref, d_ref = x_all[ref.to_numpy()], g.loc[ref, "date"].to_numpy()
        k = min(exclude_days * 2 + 2, len(x_ref))
        nn = NearestNeighbors(n_neighbors=k).fit(x_ref)
        dist, idx = nn.kneighbors(x_all)
        d_all = g["date"].to_numpy()
        nn_date, nn_dist = [], []
        for i in range(len(g)):
            chosen = None
            for dd, j in zip(dist[i], idx[i], strict=True):
                if abs((d_ref[j] - d_all[i]) / np.timedelta64(1, "D")) > exclude_days:
                    chosen = (d_ref[j], float(dd))
                    break
            nn_date.append(chosen[0] if chosen else pd.NaT)
            nn_dist.append(chosen[1] if chosen else np.nan)
        out.append(
            pd.DataFrame(
                {"date": g["date"].to_numpy(), "pair": pair, "nn_date": nn_date, "nn_dist": nn_dist}
            )
        )
    return pd.concat(out, ignore_index=True)


def score(bundle: dict, df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(contract columns, detail): anomaly_score/anomaly_pct per row + per-feature errors and the
    nearest historical neighbour. Every input at row t is known at t (causal); the reference
    distribution and neighbours come from the train period only."""
    err = reconstruction_errors(bundle, df)
    contract = df[["date", "pair"]].copy()
    contract["anomaly_score"] = err.mean(axis=1)
    contract["anomaly_pct"] = percentile_of(
        contract["anomaly_score"].to_numpy(), bundle["train_scores"]
    )
    detail = df[["date", "pair"]].copy()
    for j, f in enumerate(SIREN_FEATURES):
        detail[f"err_{f}"] = err[:, j]
    detail = detail.merge(nearest_neighbors(bundle, df), on=["date", "pair"], how="left")
    return contract, detail


# --------------------------------------------------------------------------------------
# persistence
# --------------------------------------------------------------------------------------
def model_path(version: str = SIREN_VERSION, models_dir: Path = config.MODELS_DIR) -> Path:
    return models_dir / f"siren_v{version}.joblib"


def save_bundle(bundle: dict, models_dir: Path = config.MODELS_DIR) -> Path:
    models_dir.mkdir(parents=True, exist_ok=True)
    path = model_path(bundle["version"], models_dir)
    joblib.dump(bundle, path)
    return path


def load_bundle(version: str | None = None, models_dir: Path = config.MODELS_DIR) -> dict:
    version = version or hm.read_manifest(models_dir).get("siren", {}).get("version", SIREN_VERSION)
    return joblib.load(model_path(version, models_dir))


DETAIL_PATH = config.DATA_DIR / "siren_detail.parquet"


# --------------------------------------------------------------------------------------
# known-events audit
# --------------------------------------------------------------------------------------
def _md(df: pd.DataFrame, fmt: str = "{:.1f}") -> str:
    cols = [str(c) for c in df.columns]
    out = ["| " + " | ".join(cols) + " |", "|" + "|".join(["---"] * len(cols)) + "|"]
    for _, r in df.iterrows():
        out.append(
            "| " + " | ".join(fmt.format(v) if isinstance(v, float) else str(v) for v in r) + " |"
        )
    return "\n".join(out)


def _sparkline_png(scored: pd.DataFrame, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update(
        {
            "figure.facecolor": "#0B0F17",
            "axes.facecolor": "#131A26",
            "axes.edgecolor": "#232D3F",
            "text.color": "#E7ECF4",
            "axes.labelcolor": "#E7ECF4",
            "xtick.color": "#8A94A6",
            "ytick.color": "#8A94A6",
            "grid.color": "#232D3F",
            "font.size": 9,
        }
    )
    fig, axes = plt.subplots(3, 1, figsize=(12, 7), sharex=True)
    for ax, pair in zip(axes, config.PAIRS, strict=True):
        g = scored[scored["pair"] == pair]
        ax.plot(g["date"], g["anomaly_pct"], color="#F87171", lw=0.6)
        ax.axhline(98, color="#8A94A6", ls="--", lw=0.6)
        ax.axvline(pd.Timestamp(config.VAL_START), color="#8A94A6", ls=":", lw=0.8)
        for d, label in KNOWN_EVENTS.get(pair, []):
            ax.axvline(pd.Timestamp(d), color="#FBBF24", lw=0.8)
            ax.annotate(
                label,
                (pd.Timestamp(d), 5),
                color="#FBBF24",
                fontsize=8,
                rotation=90,
                va="bottom",
                ha="right",
            )
        ax.set_ylabel(f"{pair}\nanomaly pct")
        ax.set_ylim(0, 102)
        ax.grid(alpha=0.25)
    axes[0].set_title(
        "Anomaly percentile vs calm-train distribution (dotted: out-of-sample start; dashed: 98)",
        loc="left",
    )
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def audit(scored: pd.DataFrame, bundle: dict, reports_dir: Path = config.REPORTS_DIR) -> Path:
    """reports/siren_validation.md: top-15 days per pair, known-event checks, sparkline png."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    _sparkline_png(scored, reports_dir / "siren_anomaly_pct.png")
    L = [
        "# Siren validation — does it scream at the famous shocks?\n",
        f"_Generated {datetime.now():%Y-%m-%d %H:%M}. Autoencoder {HIDDEN}, trained on {bundle['n_train']} calm train days ({bundle['train_dates'][0]} → {bundle['train_dates'][1]}, regime_prob > {CALM_PROB}), pooled across pairs, no pair identity. anomaly_pct = percentile of the reconstruction error against that calm-train distribution._\n",
    ]
    verdicts = []
    for pair in config.PAIRS:
        g = scored[scored["pair"] == pair].sort_values("anomaly_score", ascending=False)
        top = g.head(15)[["date", "anomaly_score", "anomaly_pct"]].copy()
        top["date"] = top["date"].dt.date
        L.append(f"## {pair} — 15 loudest days\n")
        L.append(_md(top.assign(anomaly_score=top["anomaly_score"].round(2)), "{:.2f}") + "\n")
        for d, label in KNOWN_EVENTS.get(pair, []):
            t = pd.Timestamp(d)
            win = scored[
                (scored["pair"] == pair)
                & (scored["date"] >= t - pd.Timedelta(days=1))
                & (scored["date"] <= t + pd.Timedelta(days=3))
            ]
            peak = win["anomaly_pct"].max() if len(win) else float("nan")
            rank = (
                int(
                    (
                        scored[scored["pair"] == pair]["anomaly_score"] > win["anomaly_score"].max()
                    ).sum()
                )
                + 1
                if len(win)
                else -1
            )
            ok = peak >= 98
            verdicts.append((pair, d, label, peak, rank, ok))
            L.append(
                f"- **{label} ({d})**: peak anomaly_pct {peak:.1f} within [−1, +3] days, rank {rank} of {int((scored['pair'] == pair).sum())} days for this pair → {'✅ lights up' if ok else '❌ does NOT light up'}.\n"
            )
    # March 2020 broadly, all pairs
    m20 = scored[(scored["date"] >= "2020-03-01") & (scored["date"] <= "2020-03-31")]
    share = (m20["anomaly_pct"] >= 98).groupby(m20["pair"]).mean()
    L.append("## March 2020, all pairs\n")
    L.append(
        "Share of March-2020 days above the 98th calm-train percentile: "
        + ", ".join(f"{p} {v:.0%}" for p, v in share.items())
        + ".\n"
    )
    L.append("## Sparkline\n![anomaly](siren_anomaly_pct.png)\n")
    L.append("## Honest reading\n")
    fails = [v for v in verdicts if not v[5]]
    L.append(
        (
            "Every named shock lights up (≥ 98th percentile within a few days of the event). "
            if not fails
            else "NOT every named shock lights up: "
            + "; ".join(f"{p} {label} peaks at {peak:.0f}" for p, d, label, peak, rank, ok in fails)
            + ". "
        )
        + "Yahoo's daily close is a start-of-day snapshot, so a shock's return shows one day late while the intraday range shows on the day — the [−1, +3]-day window accounts for that. "
        + "The siren is a detector, not a predictor: it says 'today looks unlike any calm day I learnt from', and it says it about many days that were merely volatile, not historic. Read it with the regime and the change risk, not instead of them.\n"
    )
    L.append("\n_Educational tool. Not investment advice._\n")
    out = reports_dir / "siren_validation.md"
    out.write_text("\n".join(L))
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="FX Regime Radar — anomaly siren")
    parser.add_argument(
        "--train",
        action="store_true",
        help="train, audit and save (default: score with the saved model)",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    df = joined(pd.read_parquet(config.FEATURES_PATH), pd.read_parquet(config.REGIMES_PATH))
    if args.train:
        bundle = fit_siren(df)
        path = save_bundle(bundle)
        hm.write_manifest(
            siren={
                "version": SIREN_VERSION,
                "trained_utc": datetime.now().strftime("%Y-%m-%dT%H:%MZ"),
            }
        )
        contract, _ = score(bundle, df)
        report = audit(contract, bundle)
        print(
            f"trained on {bundle['n_train']} calm days ({bundle['train_dates']}), {bundle['n_iter']} iterations -> {path}"
        )
        print(f"report -> {report}")
    else:
        bundle = load_bundle()
        contract, detail = score(bundle, df)
        print(contract.groupby("pair").tail(1).to_string(index=False))


if __name__ == "__main__":
    main()
