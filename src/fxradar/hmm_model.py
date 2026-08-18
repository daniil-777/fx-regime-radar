"""HMM regime model: fit on train only, score with FILTERED (forward-algorithm) probabilities.

One 4-state Gaussian HMM per pair on [ret_1d, vol_20, mom_20], standardised with a scaler that
is fit on the TRAIN window only (dates <= config.TRAIN_END, i.e. 2016-12-31 — chosen for
consistency with every other model in the project). Anonymous states are then named by a fixed
rule from train-period statistics and the mapping is frozen with the model.

The differentiator is `filtered_probs`: P(state_t | observations up to and including t),
computed with the forward algorithm and normalised at every step. hmmlearn's `predict_proba`
returns SMOOTHED posteriors P(state_t | ALL observations) — they use the future and are
forbidden for any output or feature (CLAUDE.md rule 1). Weather analogy: filtered is "given
everything up to today, is it a storm?"; smoothed is "knowing next week's weather too, was
today a storm?" — only the first exists in real time.
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from hmmlearn.hmm import GaussianHMM
from scipy.special import logsumexp
from scipy.stats import multivariate_normal
from sklearn.preprocessing import StandardScaler

from fxradar import config

log = logging.getLogger(__name__)

HMM_VERSION = "0.4.0"
HMM_FEATURES: list[str] = ["ret_1d", "vol_20", "mom_20"]
REGIMES: list[str] = ["calm", "trend", "chop", "crisis"]
N_STATES = 4
MIN_TRAIN_ROWS = 200  # a 4-state full-covariance HMM has ~50 parameters; refuse tiny samples
HMM_KWARGS = dict(n_components=N_STATES, covariance_type="full", n_iter=1000, random_state=42)

# columns this phase adds to features.parquet (post-HMM contract features)
POST_HMM_FEATURES: list[str] = ["hmm_entropy", "days_in_regime", "vol_trend"]
# columns of regimes.parquet written by this phase (phases 07/08 enrich in place)
REGIME_COLUMNS: list[str] = [
    "date",
    "pair",
    "regime",
    "regime_prob",
    "hmm_entropy",
    "days_in_regime",
    "model_version",
]


@dataclass
class HMMBundle:
    """Everything needed to score one pair: model + scaler + frozen state->name mapping."""

    pair: str
    model: GaussianHMM
    scaler: StandardScaler
    mapping: dict[int, str]  # anonymous state index -> regime name
    train_end: str
    version: str = HMM_VERSION
    features: list[str] = field(default_factory=lambda: list(HMM_FEATURES))


# --------------------------------------------------------------------------------------
# the forward algorithm (causal filtering)
# --------------------------------------------------------------------------------------
def frame_log_likelihood(model: GaussianHMM, X: np.ndarray) -> np.ndarray:
    """log p(x_t | state k) for every t and k under each state's Gaussian -> (n, K)."""
    X = np.asarray(X, dtype=float)
    return np.column_stack(
        [
            multivariate_normal.logpdf(X, mean=model.means_[k], cov=model.covars_[k])
            for k in range(model.n_components)
        ]
    ).reshape(len(X), model.n_components)


def filtered_probs(model: GaussianHMM, X: np.ndarray) -> np.ndarray:
    """P(state_t | x_1..x_t) for every t via the forward algorithm, normalised with logsumexp.

    alpha_0 = log(pi) + log p(x_0|k); alpha_t = logsumexp_j(alpha_{t-1,j} + log A_jk) + log p(x_t|k);
    each row is normalised so exp(alpha_t) sums to one. Only rows <= t feed row t.
    """
    log_b = frame_log_likelihood(model, X)
    log_pi = np.log(np.clip(model.startprob_, 1e-300, None))
    log_a = np.log(np.clip(model.transmat_, 1e-300, None))
    n, k = log_b.shape
    log_alpha = np.empty((n, k))
    log_alpha[0] = log_pi + log_b[0]
    log_alpha[0] -= logsumexp(log_alpha[0])
    for t in range(1, n):
        pred = logsumexp(log_alpha[t - 1][:, None] + log_a, axis=0)  # sum over previous state j
        log_alpha[t] = pred + log_b[t]
        log_alpha[t] -= logsumexp(log_alpha[t])
    return np.exp(log_alpha)


# --------------------------------------------------------------------------------------
# fitting and naming
# --------------------------------------------------------------------------------------
def train_mask(dates: pd.Series, train_end: str = config.TRAIN_END) -> pd.Series:
    """Boolean mask of training rows: dates <= train_end."""
    return dates <= pd.Timestamp(train_end)


def name_states(train_feats: pd.DataFrame, labels: np.ndarray) -> dict[int, str]:
    """Frozen naming rule from TRAIN-period per-state statistics of the RAW features.

    Sort states by mean vol_20: lowest = calm, highest = crisis; of the middle two, the one
    with the larger |mean mom_20| = trend, the other = chop. Returns a permutation of states.
    """
    stats = train_feats[HMM_FEATURES].groupby(labels).mean()
    if len(stats) != N_STATES:
        raise ValueError(f"expected {N_STATES} states present in train, got {len(stats)}")
    by_vol = stats["vol_20"].sort_values().index.tolist()
    calm, mid_a, mid_b, crisis = by_vol
    trend, chop = (
        (mid_a, mid_b)
        if abs(stats.loc[mid_a, "mom_20"]) >= abs(stats.loc[mid_b, "mom_20"])
        else (mid_b, mid_a)
    )
    return {int(calm): "calm", int(trend): "trend", int(chop): "chop", int(crisis): "crisis"}


def fit_hmm(
    feats_pair: pd.DataFrame, train_end: str = config.TRAIN_END, random_state: int = 42
) -> HMMBundle:
    """Fit scaler + HMM on the train window of one pair and freeze the state naming."""
    feats_pair = feats_pair.sort_values("date").reset_index(drop=True)
    pair = str(feats_pair["pair"].iloc[0])
    tr = feats_pair[train_mask(feats_pair["date"], train_end)]
    if len(tr) < MIN_TRAIN_ROWS:
        raise ValueError(f"{pair}: only {len(tr)} training rows before {train_end}")
    scaler = StandardScaler().fit(tr[HMM_FEATURES].to_numpy())
    model = GaussianHMM(**{**HMM_KWARGS, "random_state": random_state})
    model.fit(scaler.transform(tr[HMM_FEATURES].to_numpy()))
    labels = filtered_probs(model, scaler.transform(tr[HMM_FEATURES].to_numpy())).argmax(axis=1)
    mapping = name_states(tr, labels)
    return HMMBundle(pair=pair, model=model, scaler=scaler, mapping=mapping, train_end=train_end)


# --------------------------------------------------------------------------------------
# scoring
# --------------------------------------------------------------------------------------
def run_length(labels: pd.Series) -> pd.Series:
    """Length of the current run of identical labels, counting today (1, 2, 3, ...)."""
    new_run = labels.ne(labels.shift(1)).cumsum()
    return labels.groupby(new_run).cumcount() + 1


def score_pair(bundle: HMMBundle, feats_pair: pd.DataFrame) -> pd.DataFrame:
    """Causal regime outputs for every row of one pair, plus the post-HMM contract features."""
    feats_pair = feats_pair.sort_values("date").reset_index(drop=True)
    X = bundle.scaler.transform(feats_pair[HMM_FEATURES].to_numpy())
    probs = filtered_probs(bundle.model, X)
    state = probs.argmax(axis=1)
    out = feats_pair[["date", "pair"]].copy()
    out["regime"] = pd.Series(state).map(bundle.mapping).to_numpy()
    out["regime_prob"] = probs.max(axis=1)
    out["hmm_entropy"] = -(probs * np.log(np.clip(probs, 1e-300, None))).sum(
        axis=1
    )  # nats, max ln(4)
    out["days_in_regime"] = run_length(out["regime"]).astype("int64")
    out["vol_trend"] = np.sign(feats_pair["vol_20"] - feats_pair["vol_20"].shift(10)).fillna(0.0)
    out["model_version"] = f"hmm={bundle.version}"
    return out


def score_all(feats: pd.DataFrame, bundles: dict[str, HMMBundle]) -> pd.DataFrame:
    """Score every pair with its bundle; returns rows for all pairs, sorted by (pair, date)."""
    parts = [score_pair(bundles[p], g) for p, g in feats.groupby("pair", sort=True)]
    return pd.concat(parts, ignore_index=True).sort_values(["pair", "date"]).reset_index(drop=True)


# --------------------------------------------------------------------------------------
# persistence
# --------------------------------------------------------------------------------------
def bundle_path(
    pair: str, version: str = HMM_VERSION, models_dir: Path = config.MODELS_DIR
) -> Path:
    return models_dir / f"hmm_{pair}_v{version}.joblib"


def save_bundle(bundle: HMMBundle, models_dir: Path = config.MODELS_DIR) -> Path:
    """Persist as a plain dict of library objects — never our own classes — so the pickle does
    not depend on how this module was imported (a `python -m` run pickles classes as __main__)."""
    path = bundle_path(bundle.pair, bundle.version, models_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "pair": bundle.pair,
        "model": bundle.model,
        "scaler": bundle.scaler,
        "mapping": {int(k): str(v) for k, v in bundle.mapping.items()},
        "train_end": bundle.train_end,
        "version": bundle.version,
        "features": list(bundle.features),
    }
    joblib.dump(payload, path)
    return path


def load_bundle(
    pair: str, version: str = HMM_VERSION, models_dir: Path = config.MODELS_DIR
) -> HMMBundle:
    """Load a saved bundle and rebuild the dataclass."""
    payload = joblib.load(bundle_path(pair, version, models_dir))
    return HMMBundle(**payload)


def manifest_path(models_dir: Path = config.MODELS_DIR) -> Path:
    return models_dir / "manifest.json"


def read_manifest(models_dir: Path = config.MODELS_DIR) -> dict:
    """models/manifest.json tells the pipeline WHICH model version to load (written by refits)."""
    path = manifest_path(models_dir)
    return json.loads(path.read_text()) if path.exists() else {}


def write_manifest(models_dir: Path = config.MODELS_DIR, **entries) -> None:
    m = read_manifest(models_dir)
    m.update(entries)
    manifest_path(models_dir).write_text(json.dumps(m, indent=2))


def current_hmm_version(models_dir: Path = config.MODELS_DIR) -> str:
    return read_manifest(models_dir).get("hmm", {}).get("version", HMM_VERSION)


def load_bundles(
    pairs: list[str] | None = None, models_dir: Path = config.MODELS_DIR
) -> dict[str, HMMBundle]:
    """Load the bundles named in models/manifest.json (fallback: this module's HMM_VERSION)."""
    version = current_hmm_version(models_dir)
    return {
        p: load_bundle(p, version=version, models_dir=models_dir) for p in (pairs or config.PAIRS)
    }


# --------------------------------------------------------------------------------------
# stability check (refit with other seeds, compare labels to the seed-42 model)
# --------------------------------------------------------------------------------------
def seed_stability(
    feats: pd.DataFrame,
    bundles: dict[str, HMMBundle],
    seeds=(1, 2, 3, 4, 5),
    warn_below: float = 0.80,
) -> pd.DataFrame:
    """Refit per pair with each seed, apply the naming rule, report label agreement vs the reference."""
    rows = []
    for pair, g in feats.groupby("pair", sort=True):
        ref = score_pair(bundles[pair], g)["regime"].to_numpy()
        for seed in seeds:
            alt = fit_hmm(g, train_end=bundles[pair].train_end, random_state=seed)
            lab = score_pair(alt, g)["regime"].to_numpy()
            agree = float((lab == ref).mean())
            if agree < warn_below:
                log.warning(
                    "%s seed %d: label agreement %.1f%% < %.0f%%",
                    pair,
                    seed,
                    100 * agree,
                    100 * warn_below,
                )
            rows.append({"pair": pair, "seed": seed, "agreement": agree})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------------------
# artifacts
# --------------------------------------------------------------------------------------
def write_artifacts(feats: pd.DataFrame, regimes: pd.DataFrame) -> None:
    """regimes.parquet (contract columns) and features.parquet enriched with the post-HMM columns."""
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    regimes[REGIME_COLUMNS].to_parquet(config.REGIMES_PATH, index=False)
    enriched = feats.drop(columns=[c for c in POST_HMM_FEATURES if c in feats.columns]).merge(
        regimes[["date", "pair", *POST_HMM_FEATURES]], on=["date", "pair"], how="left"
    )
    enriched.to_parquet(config.FEATURES_PATH, index=False)


def transition_table(bundle: HMMBundle) -> pd.DataFrame:
    """Transition matrix with named rows/cols (from-state rows, to-state cols)."""
    names = [bundle.mapping[i] for i in range(N_STATES)]
    table = pd.DataFrame(bundle.model.transmat_, index=names, columns=names)
    return table.loc[REGIMES, REGIMES]  # calm, trend, chop, crisis order


def main() -> None:
    """CLI: fit (or load) per-pair HMMs, score the full history causally, write artifacts."""
    parser = argparse.ArgumentParser(description="FX Regime Radar — HMM regime model")
    parser.add_argument(
        "--refit",
        action="store_true",
        help="refit on the train window (default: load saved models). Refits are deliberate: "
        "they invalidate the frozen out-of-sample evaluation, so re-run `python -m fxradar.validate`.",
    )
    parser.add_argument(
        "--train-end", default=None, help="last training date (default config.TRAIN_END)"
    )
    parser.add_argument(
        "--version", default=None, help="version tag for the new bundles (default HMM_VERSION)"
    )
    parser.add_argument(
        "--stability", action="store_true", help="also run the 5-seed stability check"
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    feats = pd.read_parquet(config.FEATURES_PATH)
    bundles: dict[str, HMMBundle] = {}
    if args.refit:
        train_end = args.train_end or config.TRAIN_END
        version = args.version or HMM_VERSION
        for pair, g in feats.groupby("pair", sort=True):
            b = fit_hmm(g, train_end=train_end)
            b.version = version
            bundles[pair] = b
            path = save_bundle(b)
            n_train = int(train_mask(g["date"], train_end).sum())
            print(f"{pair}: fitted on {n_train} train rows (<= {train_end}) -> {path}")
        stamp = pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%dT%H:%MZ")
        write_manifest(hmm={"version": version, "train_end": train_end, "refit_utc": stamp})
        print(f"manifest -> hmm version {version}, train_end {train_end}")
    else:
        bundles = load_bundles()
        print(f"loaded hmm bundles v{current_hmm_version()} for {', '.join(bundles)}")
    regimes = score_all(feats, bundles)
    write_artifacts(feats, regimes)

    print(
        f"\nwrote {config.REGIMES_PATH} ({len(regimes)} rows) and enriched {config.FEATURES_PATH}"
    )
    print("\n== regime counts per pair ==")
    print(pd.crosstab(regimes["pair"], regimes["regime"])[REGIMES].to_string())
    print("\n== mean regime_prob per pair ==")
    print(regimes.groupby("pair")["regime_prob"].mean().round(3).to_string())
    first = config.PAIRS[0]
    print(f"\n== {first} transition matrix (rows: from, cols: to) ==")
    print(transition_table(bundles[first]).round(3).to_string())
    print("\n== state -> regime mapping ==")
    for p, b in bundles.items():
        print(p, b.mapping)
    if args.stability:
        print("\n== 5-seed stability (label agreement with the seed-42 model) ==")
        st = seed_stability(feats, bundles)
        print(st.pivot(index="pair", columns="seed", values="agreement").round(3).to_string())


if __name__ == "__main__":
    main()
