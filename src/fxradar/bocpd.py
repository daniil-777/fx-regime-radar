"""Bayesian online changepoint detection (Adams & MacKay 2007) + the three-voter consensus.

A second opinion that asks a different question than the HMM. The HMM asks "which of four
weather types is it?"; BOCPD asks "how old is the current era — did it just end?". It keeps a
posterior over the RUN LENGTH r_t (days since the last changepoint) of the daily return series,
with a Gaussian observation model whose mean and variance are unknown (Normal-Inverse-Gamma
conjugate prior → closed-form updates, Student-t predictive) and a constant hazard (prior
probability that any given day is a changepoint, default 1/60).

Everything here is ONLINE: the posterior at day t uses returns up to and including day t, so it
is causal by construction (golden rule 1) — and we still prove it with a truncation test.

Consensus (phase 21): three voters that look at the market three different ways —
  * HMM   — the filtered crisis probability over a train-era threshold,
  * BOCPD — P(changepoint within the last 5 days) over a train-era threshold,
  * VOL   — the phase-04 naive rule, reused verbatim (vol_20 above its trailing 80th pct),
summed to an agreement 0–3 with one template sentence per state. Templates only, no LLM,
no direction language.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.special import gammaln

from fxradar import config
from fxradar.validate import naive_stress

log = logging.getLogger(__name__)

HAZARD = 1.0 / 60.0  # prior changepoint probability per day (one era ≈ three months)
PRUNE = 1e-6  # run-length hypotheses below this posterior mass are dropped
HORIZON = 5  # "changepoint within the last 5 days" — the same horizon as the forecaster
PARAMS_PATH = config.MODELS_DIR / "bocpd_params.json"
BOCPD_COLUMNS = ["bocpd_run_length", "bocpd_p_change_5d"]
VOTE_COLUMNS = ["vote_hmm", "vote_bocpd", "vote_vol", "agreement", "consensus_text"]

# one sentence per agreement level — plain conditions language, never direction
CONSENSUS_TEMPLATES = {
    0: "0/3 agree: quiet conditions — no voter sees stress",
    1: "1/3 — likely a one-day spike; one voter sees stress",
    2: "2/3 agree: conditions are shifting — two voters see stress",
    3: "3/3 agree: storm conditions — every voter sees stress",
}

# fallback prior when no fitted params exist (FX daily log returns, ~0.5 % a day)
DEFAULT_PRIOR = {"mu0": 0.0, "kappa0": 1.0, "alpha0": 1.0, "beta0": 0.5 * 0.006**2}


# --------------------------------------------------------------------------------------
# the algorithm
# --------------------------------------------------------------------------------------
def _student_t_logpdf(x: float, df: np.ndarray, loc: np.ndarray, scale: np.ndarray) -> np.ndarray:
    """log density of a Student-t with `df` degrees of freedom, location `loc`, scale `scale`."""
    z = (x - loc) / scale
    return (
        gammaln((df + 1) / 2)
        - gammaln(df / 2)
        - 0.5 * np.log(df * np.pi)
        - np.log(scale)
        - (df + 1) / 2 * np.log1p(z * z / df)
    )


def bocpd(
    x: np.ndarray,
    hazard: float = HAZARD,
    prior: dict | None = None,
    prune: float = PRUNE,
    horizon: int = HORIZON,
) -> tuple[np.ndarray, np.ndarray]:
    """Run BOCPD over a 1-D series. Returns (map_run_length, p_change_within_horizon) per step.

    Observation model: x_t ~ Normal(mu, sigma^2) with (mu, sigma^2) ~ Normal-Inverse-Gamma
    (mu0, kappa0, alpha0, beta0). The predictive for a run of length r is Student-t with
    2*alpha_r degrees of freedom, location mu_r and scale^2 = beta_r (kappa_r + 1) / (alpha_r kappa_r).
    p_change = posterior mass on run lengths < horizon, i.e. "a changepoint happened within the
    last `horizon` observations (including today)".
    """
    pr = {**DEFAULT_PRIOR, **(prior or {})}
    x = np.asarray(x, dtype=float)
    n = len(x)
    map_rl = np.zeros(n, dtype=np.int64)
    p_change = np.zeros(n, dtype=float)
    # one hypothesis per run length; start with r = 0 (mass 1) and the prior parameters
    rl = np.array([0], dtype=np.int64)
    r_post = np.array([1.0])
    mu = np.array([pr["mu0"]])
    kappa = np.array([pr["kappa0"]])
    alpha = np.array([pr["alpha0"]])
    beta = np.array([pr["beta0"]])
    for t in range(n):
        xt = x[t]
        if np.isnan(xt):  # a missing return carries no evidence: keep the posterior as it is
            map_rl[t] = rl[np.argmax(r_post)]
            p_change[t] = r_post[rl < horizon].sum()
            continue
        df = 2.0 * alpha
        scale = np.sqrt(beta * (kappa + 1.0) / (alpha * kappa))
        pred = np.exp(_student_t_logpdf(xt, df, mu, scale))
        growth = r_post * pred * (1.0 - hazard)  # the run continues
        cp = float((r_post * pred * hazard).sum())  # a changepoint: run length resets to 0
        new_post = np.concatenate([[cp], growth])
        total = new_post.sum()
        if total <= 0 or not np.isfinite(total):  # numerical underflow on an absurd outlier
            new_post = np.concatenate([[1.0], np.zeros_like(growth)])
        else:
            new_post /= total
        # conjugate updates (the r = 0 hypothesis restarts from the prior)
        mu_new = np.concatenate([[pr["mu0"]], (kappa * mu + xt) / (kappa + 1.0)])
        beta_new = np.concatenate(
            [[pr["beta0"]], beta + kappa * (xt - mu) ** 2 / (2.0 * (kappa + 1.0))]
        )
        kappa_new = np.concatenate([[pr["kappa0"]], kappa + 1.0])
        alpha_new = np.concatenate([[pr["alpha0"]], alpha + 0.5])
        rl_new = np.concatenate([[0], rl + 1])
        keep = new_post >= prune
        keep[0] = True  # never drop the changepoint hypothesis
        r_post, mu, kappa, alpha, beta, rl = (
            new_post[keep],
            mu_new[keep],
            kappa_new[keep],
            alpha_new[keep],
            beta_new[keep],
            rl_new[keep],
        )
        r_post = r_post / r_post.sum()
        map_rl[t] = rl[np.argmax(r_post)]
        p_change[t] = r_post[rl < horizon].sum()
    return map_rl, p_change


def score_pair(ret_1d: pd.Series, params: dict | None = None) -> pd.DataFrame:
    """BOCPD outputs for one pair's daily returns (index preserved)."""
    params = params or {}
    map_rl, p_change = bocpd(
        ret_1d.to_numpy(dtype=float),
        hazard=float(params.get("hazard", HAZARD)),
        prior=params.get("prior"),
    )
    return pd.DataFrame(
        {"bocpd_run_length": map_rl, "bocpd_p_change_5d": p_change}, index=ret_1d.index
    )


# --------------------------------------------------------------------------------------
# train-era parameters + thresholds (the only fitted numbers; stored in models/)
# --------------------------------------------------------------------------------------
def fit_params(
    features: pd.DataFrame, regimes: pd.DataFrame, train_end: str = config.TRAIN_END
) -> dict:
    """Prior scale + voter thresholds from TRAIN rows only (≤ train_end), per pair.

    * prior beta0 = alpha0 * var(train returns) — a scale-aware but weak prior (kappa0 = 1).
    * thr_bocpd  = train-era 90th percentile of P(change ≤ 5d)  → the BOCPD voter fires ~10 % of
      train days.
    * thr_hmm    = train-era 95th percentile of the filtered crisis probability, clipped to
      [0.20, 0.50] so a pair whose crisis state is near-empty in train still needs a real signal.
    """
    out: dict = {"hazard": HAZARD, "train_end": str(train_end), "pairs": {}}
    t_end = pd.Timestamp(train_end)
    for pair, g in features.sort_values("date").groupby("pair"):
        tr = g[g["date"] <= t_end]
        r = tr["ret_1d"].dropna()
        var = float(r.var()) if len(r) > 30 else DEFAULT_PRIOR["beta0"] * 2
        prior = {"mu0": 0.0, "kappa0": 1.0, "alpha0": 1.0, "beta0": 0.5 * var}
        _, p_change = bocpd(tr["ret_1d"].to_numpy(dtype=float), prior=prior)
        rg = regimes[(regimes["pair"] == pair) & (regimes["date"] <= t_end)]
        p_crisis = rg["p_crisis"].dropna() if "p_crisis" in rg else pd.Series(dtype=float)
        thr_hmm = float(np.clip(p_crisis.quantile(0.95) if len(p_crisis) else 0.5, 0.2, 0.5))
        out["pairs"][pair] = {
            "prior": prior,
            "thr_bocpd": float(np.quantile(p_change[~np.isnan(p_change)], 0.90)),
            "thr_hmm": thr_hmm,
            "n_train": int(len(tr)),
        }
    return out


def save_params(params: dict, path: Path = PARAMS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(params, indent=1))


def load_params(path: Path = PARAMS_PATH) -> dict | None:
    return json.loads(path.read_text()) if path.exists() else None


# --------------------------------------------------------------------------------------
# consensus
# --------------------------------------------------------------------------------------
def consensus(
    regimes: pd.DataFrame, features: pd.DataFrame, params: dict | None = None
) -> pd.DataFrame:
    """Three votes + agreement + sentence per (date, pair). Returns date, pair + VOTE_COLUMNS.

    Needs `p_crisis` and `bocpd_p_change_5d` in `regimes` and `vol_20` in `features`; the vol
    voter is `validate.naive_stress` verbatim (trailing 250-day 80th percentile, causal).
    """
    params = params or load_params() or {"pairs": {}}
    parts = []
    for pair, g in regimes.sort_values("date").groupby("pair"):
        pp = params["pairs"].get(pair, {})
        thr_hmm, thr_bocpd = float(pp.get("thr_hmm", 0.5)), float(pp.get("thr_bocpd", 0.5))
        f = features[features["pair"] == pair].set_index("date")["vol_20"].reindex(g["date"])
        vol_vote = naive_stress(f.reset_index(drop=True)).to_numpy()
        out = g[["date", "pair"]].copy()
        out["vote_hmm"] = (g["p_crisis"].to_numpy(dtype=float) >= thr_hmm).astype("int64")
        out["vote_bocpd"] = (g["bocpd_p_change_5d"].to_numpy(dtype=float) >= thr_bocpd).astype(
            "int64"
        )
        out["vote_vol"] = np.asarray(vol_vote, dtype=bool).astype("int64")
        out["agreement"] = out[["vote_hmm", "vote_bocpd", "vote_vol"]].sum(axis=1).astype("int64")
        out["consensus_text"] = out["agreement"].map(CONSENSUS_TEMPLATES)
        parts.append(out)
    return pd.concat(parts, ignore_index=True)


def score_all(
    regimes: pd.DataFrame, features: pd.DataFrame, params: dict | None = None
) -> pd.DataFrame:
    """BOCPD per pair + consensus, merged onto `regimes` (new columns only; rows untouched)."""
    params = params or load_params() or {"pairs": {}}
    parts = []
    for pair, g in features.sort_values("date").groupby("pair"):
        sc = score_pair(g["ret_1d"], params["pairs"].get(pair))
        parts.append(
            pd.concat(
                [g[["date", "pair"]].reset_index(drop=True), sc.reset_index(drop=True)], axis=1
            )
        )
    boc = pd.concat(parts, ignore_index=True)
    out = regimes.drop(columns=[c for c in BOCPD_COLUMNS + VOTE_COLUMNS if c in regimes.columns])
    out = out.merge(boc, on=["date", "pair"], how="left")
    votes = consensus(out, features, params)
    return out.merge(votes, on=["date", "pair"], how="left")


def stage(ctx: dict) -> None:
    """run_daily stage: BOCPD + consensus columns onto ctx['regimes'] (fitted params from models/)."""
    params = load_params()
    if params is None:  # first run on a fresh universe: fit on train rows and persist
        params = fit_params(ctx["features"], ctx["regimes"])
        save_params(params)
        log.info("bocpd: fitted train-era params → %s", PARAMS_PATH)
    ctx["regimes"] = score_all(ctx["regimes"], ctx["features"], params)
    latest = ctx["regimes"].sort_values("date").groupby("pair").tail(1)
    log.info(
        "bocpd: %s",
        ", ".join(
            f"{r.pair} run={int(r.bocpd_run_length)} p5={r.bocpd_p_change_5d:.2f} {int(r.agreement)}/3"
            for r in latest.itertuples()
        ),
    )


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="BOCPD + consensus from committed artifacts")
    ap.add_argument("--fit", action="store_true", help="(re)fit train-era params into models/")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    feats = pd.read_parquet(config.FEATURES_PATH)
    regimes = pd.read_parquet(config.REGIMES_PATH)
    if args.fit or not PARAMS_PATH.exists():
        save_params(fit_params(feats, regimes))
        log.info("wrote %s", PARAMS_PATH)
    scored = score_all(regimes, feats)
    print(
        scored.sort_values("date")
        .groupby("pair")
        .tail(1)[["date", "pair", *BOCPD_COLUMNS, *VOTE_COLUMNS]]
        .to_string(index=False)
    )
    print(json.dumps(load_params(), indent=1))


if __name__ == "__main__":
    main()
