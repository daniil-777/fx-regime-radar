"""A choice of estimators for the 5-day change-risk forecaster — one protocol, three engines.

Why these three (research: see README "Model choice"): gradient-boosted trees remain state of the
art on tabular data at this scale (~9k train rows × 15 features — Grinsztajn et al. 2022;
McElfresh et al. 2023); TabPFN-class foundation models are interesting below ~10k rows but need
torch, which this repo's CI bans by design (rule: sklearn-only, five-minute CI).

* xgb    — the shipped champion, delegated verbatim to `forecaster.fit_forecaster` (fixed
           hyper-parameters, early stopping on validation PR-AUC). Untouched.
* histgb — scikit-learn's HistGradientBoostingClassifier: the LightGBM-style histogram GBDT that
           ships inside sklearn — a genuinely different implementation (native NaN handling,
           leaf-wise histograms, L2 on leaves) at zero new dependencies. The tree count is chosen
           on VALIDATION by PR-AUC over a small explicit grid — no random validation_fraction,
           which would break the time ordering.
* logistic — the linear reference, promoted from baseline to a selectable engine.

Every engine goes through the SAME protocol as the champion: fit on train, select on validation,
Platt-recalibrate on validation, threshold at recall ≥ TARGET_RECALL on validation, score the
frozen test ONCE. There is deliberately NO env switch for the daily path: a new estimator reaches
production only through the challenger-ledger protocol (train here, race on the live ledger under
its own model_version, promote by a deliberate refit-path act).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from fxradar import forecaster as fc

ESTIMATORS = ("xgb", "histgb", "logistic")
HISTGB_GRID = (100, 200, 400)  # max_iter chosen on validation PR-AUC — explicit, time-ordered
HISTGB_PARAMS = dict(
    learning_rate=0.05,
    max_leaf_nodes=15,
    min_samples_leaf=40,
    l2_regularization=1.0,
    class_weight="balanced",
    random_state=42,
)


def fit_estimator(
    name: str, x_tr: pd.DataFrame, y_tr: pd.Series, x_va: pd.DataFrame, y_va: pd.Series
):
    """Fit one engine under the champion's protocol. Returns (model, info dict)."""
    if name == "xgb":
        df = pd.concat(
            [
                x_tr.assign(y=y_tr.to_numpy(), split="train"),
                x_va.assign(y=y_va.to_numpy(), split="val"),
            ],
            ignore_index=True,
        )
        return fc.fit_forecaster(df)  # the champion path, verbatim
    if name == "histgb":
        best, best_ap, val_scores = None, -1.0, {}
        for n in HISTGB_GRID:
            m = HistGradientBoostingClassifier(max_iter=n, **HISTGB_PARAMS)
            m.fit(x_tr, y_tr)
            ap = float(average_precision_score(y_va, m.predict_proba(x_va)[:, 1]))
            val_scores[n] = round(ap, 4)
            if ap > best_ap:
                best, best_ap = m, ap
        return best, {"max_iter_grid_val_pr_auc": val_scores, "chosen_max_iter": best.max_iter}
    if name == "logistic":
        m = make_pipeline(
            StandardScaler(), LogisticRegression(max_iter=2000, class_weight="balanced")
        )
        m.fit(x_tr, y_tr)
        ap = float(average_precision_score(y_va, m.predict_proba(x_va)[:, 1]))
        return m, {"val_pr_auc": round(ap, 4)}
    raise KeyError(f"unknown estimator {name!r}; choose from {ESTIMATORS}")


def raw_proba(name: str, model, x: pd.DataFrame) -> np.ndarray:
    return np.asarray(model.predict_proba(x)[:, 1], dtype=float)


def evaluate(name: str, df: pd.DataFrame) -> dict:
    """Train + select + calibrate + threshold + score, exactly like the champion's report path.
    `df` is `forecaster.assemble(...)` output. The test split is scored once, here."""
    tr = df[(df["split"] == "train") & df["y"].notna()]
    va = df[(df["split"] == "val") & df["y"].notna()]
    te = df[(df["split"] == "test") & df["y"].notna()]
    model, info = fit_estimator(
        name, tr[fc.FEATURES], tr["y"].astype(int), va[fc.FEATURES], va["y"].astype(int)
    )
    p_va = raw_proba(name, model, va[fc.FEATURES])
    a, b = fc.fit_calibrator(p_va, va["y"].to_numpy(dtype=float))
    p_va_cal = fc.calibrate(p_va, a, b)
    thr = fc.choose_threshold(p_va_cal, va["y"].to_numpy(dtype=float))
    p_te_cal = fc.calibrate(raw_proba(name, model, te[fc.FEATURES]), a, b)
    return {
        "estimator": name,
        "model": model,
        "info": info,
        "calibration": {"a": round(a, 4), "b": round(b, 4)},
        "threshold": thr,
        "val": fc.metrics(va["y"].to_numpy(dtype=float), p_va_cal, thr),
        "test": fc.metrics(te["y"].to_numpy(dtype=float), p_te_cal, thr),
    }
