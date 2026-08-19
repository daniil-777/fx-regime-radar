"""A choice of regime models behind one contract — the champion HMM, a statistical jump model,
and a mixture baseline.

Why these three (research: see README "Model choice"):
* HMM        — the shipped champion (phase 03): filtered forward algorithm, wall-protected for fx.
* JUMP       — the statistical jump model (Bemporad et al. 2018, Automatica; Nystrup, Lindström &
               Madsen 2020/21; Aydınhan, Kolm, Mulvey & Shu 2024, Annals of OR): k-means-style
               state centres plus an explicit penalty λ for every state switch. It is the modern
               industry alternative to the HMM, built to fix exactly the weakness our own
               validation report documents — state sequences that flicker, and a fragile
               trend/chop split. Fitting uses coordinate descent (dynamic programme over the TRAIN
               sequence ↔ centre updates); daily inference is the GREEDY ONLINE rule from Nystrup
               et al. (2020), which sees only days ≤ t — causal by construction, and proven by the
               same bit-for-bit truncation test as everything else.
* GMM        — a Gaussian mixture with NO temporal coupling: the ablation that shows what the
               persistence machinery (transition matrix / jump penalty) is buying.

Every model implements the same contract as `hmm_model.score_all`: the REGIME_COLUMNS frame with
filtered probabilities, entropy, run length and `model_version`, states named by the SAME frozen
rule (`hmm_model.name_states`), scalers fitted on TRAIN rows only.

Selection: `FXRADAR_REGIME_MODEL` (default "hmm"). The `fx` universe is HARD-LOCKED to "hmm" —
its bundle, golden vectors, Rust wall and live ledger segment define the public record; a regime
model swap there is a deliberate refit-path act, never an env var. Other universes may select any
registered model; the daily pipeline then scores with it under its own `model_version` string, so
the ledger opens a new segment and the old record stays untouched (rule: never launder).
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass, field
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.mixture import GaussianMixture
from sklearn.preprocessing import StandardScaler

from fxradar import config
from fxradar import hmm_model as hm

log = logging.getLogger(__name__)

JUMP_VERSION = "0.1.0"
GMM_VERSION = "0.1.0"
N_STATES = hm.N_STATES
FEATURES = (
    hm.HMM_FEATURES
)  # the same three inputs for every model — differences are model, not data
TEMPERATURE = (
    2.0  # jump/gmm probability proxy: softmax(-cost / T); display confidence, not a posterior
)
LAMBDA_GRID = (
    0.25,
    0.5,
    1.0,
    2.0,
    4.0,
    8.0,
)  # greedy-online scale: a switch needs a one-day advantage > λ


# ======================================================================================
# the statistical jump model
# ======================================================================================
@dataclass
class JumpBundle:
    pair: str
    centers: np.ndarray  # (K, F) in standardised space
    scaler: StandardScaler
    mapping: dict[int, str]
    lam: float
    train_end: str
    version: str = JUMP_VERSION
    features: list[str] = field(default_factory=lambda: list(FEATURES))

    @property
    def model_version(self) -> str:
        return f"jump={self.version}|lam={self.lam:g}"


def _viterbi_states(X: np.ndarray, centers: np.ndarray, lam: float) -> np.ndarray:
    """Offline dynamic programme (FIT ONLY, train rows): the state sequence minimising
    Σ_t ½‖x_t − μ_{s_t}‖² + λ Σ_t 1[s_t ≠ s_{t−1}]."""
    d = 0.5 * ((X[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2)  # (T, K)
    T, K = d.shape
    cost = d[0].copy()
    back = np.zeros((T, K), dtype=np.int64)
    for t in range(1, T):
        trans = cost[None, :] + lam * (1 - np.eye(K))  # cost of arriving in k from j
        back[t] = trans.argmin(axis=1)
        cost = d[t] + trans[np.arange(K), back[t]]
    states = np.empty(T, dtype=np.int64)
    states[-1] = int(cost.argmin())
    for t in range(T - 2, -1, -1):
        states[t] = back[t + 1, states[t + 1]]
    return states


def _greedy_online(X: np.ndarray, centers: np.ndarray, lam: float) -> tuple[np.ndarray, np.ndarray]:
    """CAUSAL inference (Nystrup et al. 2020, greedy online rule): at day t the state may switch
    only if the new centre is closer by more than λ. Returns (states, probs) where probs is the
    softmax confidence proxy over the per-day costs. Only rows ≤ t feed row t."""
    d = 0.5 * ((X[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2)
    T, K = d.shape
    states = np.empty(T, dtype=np.int64)
    probs = np.empty((T, K))
    prev = int(d[0].argmin())
    for t in range(T):
        cost = d[t] + lam * (np.arange(K) != prev)
        if t == 0:
            cost = d[0]
        states[t] = int(cost.argmin())
        z = -(cost - cost.min()) / TEMPERATURE
        e = np.exp(z)
        probs[t] = e / e.sum()
        prev = int(states[t])
    return states, probs


def fit_jump(
    feats_pair: pd.DataFrame,
    train_end: str = config.TRAIN_END,
    lam: float = 2.0,
    random_state: int = 42,
    n_sweeps: int = 30,
) -> JumpBundle:
    """Fit centres + naming on the TRAIN window of one pair (coordinate descent)."""
    feats_pair = feats_pair.sort_values("date").reset_index(drop=True)
    pair = str(feats_pair["pair"].iloc[0])
    tr = feats_pair[hm.train_mask(feats_pair["date"], train_end)]
    if len(tr) < hm.MIN_TRAIN_ROWS:
        raise ValueError(f"{pair}: only {len(tr)} training rows before {train_end}")
    scaler = StandardScaler().fit(tr[FEATURES].to_numpy())
    X = scaler.transform(tr[FEATURES].to_numpy())
    centers = (
        KMeans(n_clusters=N_STATES, n_init=10, random_state=random_state).fit(X).cluster_centers_
    )
    states = _viterbi_states(X, centers, lam)
    for _ in range(n_sweeps):
        new_centers = np.vstack(
            [
                X[states == k].mean(axis=0) if (states == k).any() else centers[k]
                for k in range(N_STATES)
            ]
        )
        new_states = _viterbi_states(X, new_centers, lam)
        converged = np.array_equal(new_states, states)
        centers, states = new_centers, new_states
        if converged:
            break
    mapping = hm.name_states(tr, states)
    return JumpBundle(
        pair=pair, centers=centers, scaler=scaler, mapping=mapping, lam=lam, train_end=train_end
    )


def pick_lambda(
    feats_pair: pd.DataFrame,
    reference_switches_per_year: float,
    train_end: str = config.TRAIN_END,
    grid: tuple[float, ...] = LAMBDA_GRID,
) -> float:
    """λ is a persistence prior (like BOCPD's hazard). Chosen ON TRAIN ONLY: the grid value whose
    train-era switching rate is closest to the champion HMM's — so the two models are compared at
    matched persistence rather than λ being tuned on anything out of sample."""
    feats_pair = feats_pair.sort_values("date").reset_index(drop=True)
    tr = feats_pair[hm.train_mask(feats_pair["date"], train_end)]
    years = max(len(tr) / config.TRADING_DAYS, 1e-9)
    best, best_gap = grid[0], float("inf")
    for lam in grid:
        b = fit_jump(feats_pair, train_end=train_end, lam=lam)
        X = b.scaler.transform(tr[FEATURES].to_numpy())
        states, _ = _greedy_online(X, b.centers, lam)
        switches = float((states[1:] != states[:-1]).sum()) / years
        gap = abs(switches - reference_switches_per_year)
        if gap < best_gap:
            best, best_gap = lam, gap
    return best


# ======================================================================================
# the mixture baseline (no temporal coupling — the ablation)
# ======================================================================================
@dataclass
class GMMBundle:
    pair: str
    model: GaussianMixture
    scaler: StandardScaler
    mapping: dict[int, str]
    train_end: str
    version: str = GMM_VERSION
    features: list[str] = field(default_factory=lambda: list(FEATURES))

    @property
    def model_version(self) -> str:
        return f"gmm={self.version}"


def fit_gmm(
    feats_pair: pd.DataFrame, train_end: str = config.TRAIN_END, random_state: int = 42
) -> GMMBundle:
    feats_pair = feats_pair.sort_values("date").reset_index(drop=True)
    pair = str(feats_pair["pair"].iloc[0])
    tr = feats_pair[hm.train_mask(feats_pair["date"], train_end)]
    if len(tr) < hm.MIN_TRAIN_ROWS:
        raise ValueError(f"{pair}: only {len(tr)} training rows before {train_end}")
    scaler = StandardScaler().fit(tr[FEATURES].to_numpy())
    model = GaussianMixture(
        n_components=N_STATES, covariance_type="full", n_init=5, random_state=random_state
    ).fit(scaler.transform(tr[FEATURES].to_numpy()))
    labels = model.predict(scaler.transform(tr[FEATURES].to_numpy()))
    mapping = hm.name_states(tr, labels)
    return GMMBundle(pair=pair, model=model, scaler=scaler, mapping=mapping, train_end=train_end)


# ======================================================================================
# one scoring contract for all of them
# ======================================================================================
def _contract_frame(
    feats_pair: pd.DataFrame, probs: np.ndarray, mapping: dict[int, str], model_version: str
) -> pd.DataFrame:
    """The REGIME_COLUMNS frame from per-day state probabilities (same shape as hm.score_pair)."""
    state = probs.argmax(axis=1)
    out = feats_pair[["date", "pair"]].copy()
    out["regime"] = pd.Series(state).map(mapping).to_numpy()
    out["regime_prob"] = probs.max(axis=1)
    out["hmm_entropy"] = -(probs * np.log(np.clip(probs, 1e-300, None))).sum(axis=1)
    out["days_in_regime"] = hm.run_length(out["regime"]).astype("int64")
    for s, name in mapping.items():
        out[f"p_{name}"] = probs[:, s]
    out["vol_trend"] = np.sign(feats_pair["vol_20"] - feats_pair["vol_20"].shift(10)).fillna(0.0)
    out["model_version"] = model_version
    return out


def score_pair(bundle, feats_pair: pd.DataFrame) -> pd.DataFrame:
    """Causal regime outputs for one pair under any registered bundle type."""
    feats_pair = feats_pair.sort_values("date").reset_index(drop=True)
    if isinstance(bundle, hm.HMMBundle):
        return hm.score_pair(bundle, feats_pair)  # the champion path, byte-identical
    X = bundle.scaler.transform(feats_pair[FEATURES].to_numpy())
    if isinstance(bundle, JumpBundle):
        _, probs = _greedy_online(X, bundle.centers, bundle.lam)
    elif isinstance(bundle, GMMBundle):
        probs = bundle.model.predict_proba(X)  # per-day, no temporal coupling
    else:  # pragma: no cover - registry guards this
        raise TypeError(f"unknown bundle type {type(bundle)!r}")
    return _contract_frame(feats_pair, probs, bundle.mapping, bundle.model_version)


def score_all(feats: pd.DataFrame, bundles: dict) -> pd.DataFrame:
    parts = [score_pair(bundles[p], g) for p, g in feats.groupby("pair", sort=True)]
    return pd.concat(parts, ignore_index=True).sort_values(["pair", "date"]).reset_index(drop=True)


# ======================================================================================
# registry, persistence, selection
# ======================================================================================
MODELS = ("hmm", "jump", "gmm")


def selected_model() -> str:
    """The active regime model. fx is hard-locked to the champion HMM (wall + public ledger)."""
    name = config.REGIME_MODEL
    if name not in MODELS:
        raise KeyError(f"unknown regime model {name!r}; choose from {MODELS}")
    if config.UNIVERSE_NAME == "fx" and name != "hmm":
        raise RuntimeError(
            "the fx universe is locked to the champion HMM: its bundle, golden vectors and live "
            "ledger define the public record — swapping the regime model there is a deliberate "
            "refit-path act, not an environment variable"
        )
    return name


def bundle_path(name: str, pair: str, models_dir: Path | None = None) -> Path:
    d = models_dir or config.MODELS_DIR
    version = {"jump": JUMP_VERSION, "gmm": GMM_VERSION}[name]
    return d / f"regime_{name}_{pair}_v{version}.joblib"


def save_bundles(name: str, bundles: dict, models_dir: Path | None = None) -> None:
    for pair, b in bundles.items():
        path = bundle_path(name, pair, models_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(b, path)


def load_bundles(name: str | None = None, models_dir: Path | None = None) -> dict:
    """Saved bundles for the selected model ('hmm' delegates to the champion loader)."""
    name = name or selected_model()
    if name == "hmm":
        return hm.load_bundles(models_dir=models_dir) if models_dir else hm.load_bundles()
    out = {}
    for pair in config.PAIRS:
        path = bundle_path(name, pair, models_dir)
        if not path.exists():
            raise FileNotFoundError(
                f"{path} missing — train it first: python -m fxradar.regime_models --train --model {name}"
            )
        out[pair] = joblib.load(path)
    return out


def train(name: str, feats: pd.DataFrame, lam: float | None = None) -> dict:
    """Fit the chosen model for every pair (train rows only). For 'jump' with lam=None the penalty
    is picked per pair on TRAIN by matching the champion HMM's switching rate (see pick_lambda)."""
    bundles = {}
    for pair, g in feats.groupby("pair", sort=True):
        if name == "jump":
            pair_lam = lam
            if pair_lam is None:
                hb = hm.load_bundles()[pair]
                tr = g[hm.train_mask(g["date"])]
                ref_states = hm.filtered_probs(
                    hb.model, hb.scaler.transform(tr[FEATURES].to_numpy())
                ).argmax(axis=1)
                years = max(len(tr) / config.TRADING_DAYS, 1e-9)
                ref_switches = float((ref_states[1:] != ref_states[:-1]).sum()) / years
                pair_lam = pick_lambda(g, ref_switches)
            bundles[pair] = fit_jump(g, lam=pair_lam)
            log.info("jump %s: lam=%g", pair, pair_lam)
        elif name == "gmm":
            bundles[pair] = fit_gmm(g)
        elif name == "hmm":
            bundles[pair] = hm.fit_hmm(g)
        else:
            raise KeyError(name)
    return bundles


def main() -> None:
    ap = argparse.ArgumentParser(description="Regime-model registry: train / score alternatives")
    ap.add_argument("--train", action="store_true")
    ap.add_argument("--model", default=None, choices=MODELS)
    ap.add_argument(
        "--lam", type=float, default=None, help="jump penalty (default: matched to HMM on train)"
    )
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    name = args.model or selected_model()
    feats = pd.read_parquet(config.FEATURES_PATH)
    if args.train:
        if name == "hmm":
            raise SystemExit(
                "the champion HMM is trained via `python -m fxradar.hmm_model --refit`"
            )
        bundles = train(name, feats, lam=args.lam)
        save_bundles(name, bundles)
        print(f"saved {len(bundles)} {name} bundles -> {config.MODELS_DIR}")
    bundles = load_bundles(name)
    scored = score_all(feats, bundles)
    print(
        scored.sort_values("date")
        .groupby("pair")
        .tail(1)[["date", "pair", "regime", "regime_prob", "days_in_regime", "model_version"]]
        .to_string(index=False)
    )


if __name__ == "__main__":
    main()
