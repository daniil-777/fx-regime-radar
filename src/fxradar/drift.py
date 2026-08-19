"""Drift monitor: is the world the models were fitted on still the world they score?

Three honest, cheap checks, written to data/status.json with a `model_stale` flag:
  * PSI per feature — 10 quantile bins fitted on TRAIN rows (≤ train_end) only; the last 60 days
    are binned the same way. The textbook cut-offs (0.10 watch / 0.25 drifted) are reported, but
    a 60-day window of a slow, regime-switching feature (vol_20 has ~3 independent observations
    in 60 days) sits at PSI 3–8 against the whole era EVEN INSIDE TRAIN, so the status is judged
    against the train-era distribution of 60-day-window PSIs: > train p95 = drifted, > p75 = watch.
  * KS — two-sample Kolmogorov–Smirnov statistic, train era vs last 60 days, per feature.
  * HMM staleness — mean per-day filtered (predictive) log-likelihood of the last 60 days under
    each pair's SAVED HMM, compared with the train-era distribution of the same quantity: if it
    sits below the train 5th percentile the model is flagged stale for that pair.
`model_stale` is True when any pair's HMM is stale or any feature is "drifted".
Nothing here refits anything: a stale flag is a message to the human who owns `make refit`.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.special import logsumexp
from scipy.stats import ks_2samp

from fxradar import config
from fxradar import hmm_model as hm

log = logging.getLogger(__name__)

STATUS_PATH = config.DATA_DIR / "status.json"
FEATURES = [
    "ret_1d",
    "vol_20",
    "vol_60",
    "vol_ratio",
    "mom_20",
    "rng_hl",
    "corr_20",
    "ret_5d_abs",
    "hmm_entropy",
]
WINDOW = 60  # "recent" = the last 60 trading days
N_BINS = 10
PSI_WATCH, PSI_DRIFTED = 0.10, 0.25
STALE_PCT = 5  # HMM stale if recent mean log-lik < train 5th percentile of 60-day means


def psi(train: np.ndarray, recent: np.ndarray, n_bins: int = N_BINS) -> float:
    """Population stability index with quantile bins fitted on `train` (NaNs dropped)."""
    train = np.asarray(train, dtype=float)
    recent = np.asarray(recent, dtype=float)
    train, recent = train[~np.isnan(train)], recent[~np.isnan(recent)]
    if len(train) < n_bins * 5 or len(recent) == 0:
        return float("nan")
    edges = np.unique(np.quantile(train, np.linspace(0, 1, n_bins + 1)))
    edges[0], edges[-1] = -np.inf, np.inf
    e = np.histogram(train, bins=edges)[0] / len(train)
    a = np.histogram(recent, bins=edges)[0] / len(recent)
    e, a = np.clip(e, 1e-4, None), np.clip(a, 1e-4, None)
    return float(np.sum((a - e) * np.log(a / e)))


def psi_label(value: float, watch: float = PSI_WATCH, drifted: float = PSI_DRIFTED) -> str:
    if np.isnan(value):
        return "n/a"
    return "drifted" if value > drifted else "watch" if value > watch else "stable"


def psi_reference(
    features: pd.DataFrame, feature: str, train_end: str, window: int, step: int = 20
) -> np.ndarray:
    """PSI of every train-era `window`-day slice (per pair, every `step` days) vs the whole train era."""
    t_end = pd.Timestamp(train_end)
    train = features[features["date"] <= t_end]
    base = train[feature].to_numpy(dtype=float)
    vals = []
    for _, g in train.groupby("pair"):
        x = g.sort_values("date")[feature].to_numpy(dtype=float)
        for s in range(window, len(x) + 1, step):
            vals.append(psi(base, x[s - window : s]))
    return np.asarray(vals, dtype=float)


def predictive_loglik(model, X: np.ndarray) -> np.ndarray:
    """log p(x_t | x_1..x_{t-1}) per day under the saved HMM (the forward pass's normaliser)."""
    log_b = hm.frame_log_likelihood(model, X)
    log_pi = np.log(np.clip(model.startprob_, 1e-300, None))
    log_a = np.log(np.clip(model.transmat_, 1e-300, None))
    n, _ = log_b.shape
    out = np.empty(n)
    log_alpha = log_pi + log_b[0]
    out[0] = logsumexp(log_alpha)
    log_alpha -= out[0]
    for t in range(1, n):
        pred = logsumexp(log_alpha[:, None] + log_a, axis=0)
        log_alpha = pred + log_b[t]
        out[t] = logsumexp(log_alpha)
        log_alpha -= out[t]
    return out


def hmm_staleness(
    features: pd.DataFrame, bundles: dict, train_end: str = config.TRAIN_END, window: int = WINDOW
) -> dict:
    """Per pair: recent mean per-day log-lik vs the train-era distribution of rolling means."""
    out = {}
    t_end = pd.Timestamp(train_end)
    for pair, b in bundles.items():
        g = features[features["pair"] == pair].sort_values("date")
        X = b.scaler.transform(g[hm.HMM_FEATURES].to_numpy())
        ll = pd.Series(predictive_loglik(b.model, X), index=g["date"].to_numpy())
        roll = ll.rolling(window).mean().dropna()
        train_means = roll[roll.index <= t_end]
        recent = float(roll.iloc[-1]) if len(roll) else float("nan")
        p5 = float(np.percentile(train_means, STALE_PCT)) if len(train_means) else float("nan")
        out[pair] = {
            "recent_mean_loglik": round(recent, 4),
            "train_p5": round(p5, 4),
            "train_median": round(float(train_means.median()), 4) if len(train_means) else None,
            "stale": bool(recent < p5) if np.isfinite(recent) and np.isfinite(p5) else False,
        }
    return out


def feature_drift(
    features: pd.DataFrame, train_end: str = config.TRAIN_END, window: int = WINDOW
) -> dict:
    """PSI + KS per feature, pooled across pairs (train era vs the last `window` days per pair)."""
    t_end = pd.Timestamp(train_end)
    out = {}
    recent_parts = [g.sort_values("date").tail(window) for _, g in features.groupby("pair")]
    recent = pd.concat(recent_parts)
    train = features[features["date"] <= t_end]
    for f in FEATURES:
        if f not in features.columns:
            continue
        tr, rc = train[f].to_numpy(dtype=float), recent[f].to_numpy(dtype=float)
        tr, rc = tr[~np.isnan(tr)], rc[~np.isnan(rc)]
        value = psi(tr, rc)
        ks = float(ks_2samp(tr, rc).statistic) if len(tr) and len(rc) else float("nan")
        ref = psi_reference(features, f, train_end, window)
        ref = ref[np.isfinite(ref)]
        p75, p95 = (
            (float(np.percentile(ref, 75)), float(np.percentile(ref, 95)))
            if len(ref)
            else (PSI_WATCH, PSI_DRIFTED)
        )
        out[f] = {
            "psi": round(value, 4),
            "status": psi_label(value, p75, p95),
            "textbook": psi_label(value),
            "train_p75": round(p75, 4),
            "train_p95": round(p95, 4),
            "ks": round(ks, 4),
        }
    return out


def status(
    features: pd.DataFrame, bundles: dict | None = None, generated_at_utc: str | None = None
) -> dict:
    bundles = bundles if bundles is not None else hm.load_bundles()
    feats = feature_drift(features)
    hmm = hmm_staleness(features, bundles)
    drifted = [f for f, v in feats.items() if v["status"] == "drifted"]
    stale_pairs = [p for p, v in hmm.items() if v["stale"]]
    return {
        "generated_at_utc": generated_at_utc or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data_through": str(features["date"].max().date()),
        "window_days": WINDOW,
        "train_end": str(config.TRAIN_END),
        "thresholds": {
            "psi_watch": PSI_WATCH,
            "psi_drifted": PSI_DRIFTED,
            "hmm_stale_pct": STALE_PCT,
        },
        "features": feats,
        "hmm": hmm,
        "drifted_features": drifted,
        "stale_pairs": stale_pairs,
        "model_stale": bool(drifted or stale_pairs),
        "worst_psi": max((v["psi"] for v in feats.values() if np.isfinite(v["psi"])), default=None),
    }


def stage(ctx: dict) -> None:
    """run_daily stage: drift status from the freshly built features + saved HMMs → status.json."""
    ctx["status"] = status(ctx["features"])
    ctx.setdefault("extra_writers", {})["status.json"] = lambda c: write_status(c["status"])
    s = ctx["status"]
    log.info(
        "drift: model_stale=%s worst PSI %.3f drifted=%s stale=%s",
        s["model_stale"],
        s["worst_psi"] or float("nan"),
        s["drifted_features"],
        s["stale_pairs"],
    )


def write_status(s: dict, path: Path = STATUS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(s, indent=1, default=float))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    feats = pd.read_parquet(config.FEATURES_PATH)
    s = status(feats)
    write_status(s)
    print(json.dumps({k: v for k, v in s.items() if k != "features"}, indent=1, default=float))
    print(pd.DataFrame(s["features"]).T.to_string())


if __name__ == "__main__":
    main()
