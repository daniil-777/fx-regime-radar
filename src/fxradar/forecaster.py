"""XGBoost forecaster of 5-day regime-change risk, with SHAP driver explanations.

Question answered: "will the filtered regime label be different at any point in the next five
trading days?" Labels look forward (allowed); every feature at t is causal (CLAUDE.md rule 1),
including the HMM-derived ones, which come from the FILTERED outputs of phase 03. Splits are
time-ordered with a 5-trading-day embargo on both sides of every boundary (rule 2). Accuracy
is never reported (rule 3): PR-AUC, precision/recall on transitions, Brier + calibration, and a
scoreboard against three baselines.
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.calibration import calibration_curve
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, precision_score, recall_score
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

from fxradar import config
from fxradar import hmm_model as hm

log = logging.getLogger(__name__)

FORECASTER_VERSION = "1.1.0"
HORIZON = 5  # trading days
NUMERIC_FEATURES: list[str] = [
    "vol_20",
    "vol_60",
    "vol_ratio",
    "mom_20",
    "rng_hl",
    "corr_20",
    "ret_5d_abs",
    "days_in_regime",
    "hmm_entropy",
    "vol_trend",
]
REGIME_DUMMIES: list[str] = ["regime_trend", "regime_chop", "regime_crisis"]  # calm = base
PAIR_DUMMIES: list[str] = ["pair_GBPUSD", "pair_USDCHF"]  # EURUSD = base
FEATURES: list[str] = [*NUMERIC_FEATURES, *REGIME_DUMMIES, *PAIR_DUMMIES]

# Restraint is deliberate: no grid search. These are sane defaults for ~9k rows x 15 features;
# tuning on validation would buy little and cost credibility (rule 2: the test set is scored once).
XGB_PARAMS = dict(
    n_estimators=1000,
    early_stopping_rounds=50,
    max_depth=3,
    learning_rate=0.04,
    subsample=0.8,
    colsample_bytree=0.8,
    min_child_weight=8,
    eval_metric="aucpr",
    random_state=42,
    n_jobs=4,
)
TARGET_RECALL = 0.6


# --------------------------------------------------------------------------------------
# dataset assembly (pooled across pairs)
# --------------------------------------------------------------------------------------
def build_matrix(features: pd.DataFrame, regimes: pd.DataFrame) -> pd.DataFrame:
    """Pooled design matrix: date, pair, regime + FEATURES. Everything at row t is known at t."""
    df = features.merge(regimes[["date", "pair", "regime"]], on=["date", "pair"], how="inner")
    df = df.sort_values(["pair", "date"]).reset_index(drop=True)
    for r in ["trend", "chop", "crisis"]:
        df[f"regime_{r}"] = (df["regime"] == r).astype(float)
    for p in ["GBPUSD", "USDCHF"]:
        df[f"pair_{p}"] = (df["pair"] == p).astype(float)
    return df[["date", "pair", "regime", *FEATURES]]


def build_labels(matrix: pd.DataFrame, horizon: int = HORIZON) -> pd.Series:
    """y_t = 1 if the regime at any of t+1..t+horizon differs from the regime at t; NaN for the
    final `horizon` rows per pair (incomplete future window)."""
    y = pd.Series(np.nan, index=matrix.index, dtype=float)
    for _, g in matrix.groupby("pair", sort=False):
        reg = g["regime"]
        changed = pd.Series(False, index=g.index)
        for k in range(1, horizon + 1):
            changed |= reg.shift(-k).ne(reg)
        changed.iloc[-horizon:] = False
        vals = changed.astype(float)
        vals.iloc[-horizon:] = np.nan
        y.loc[g.index] = vals
    return y


def assign_splits(matrix: pd.DataFrame, embargo: int = config.EMBARGO_DAYS) -> pd.Series:
    """train / val / test / embargo per row, time-ordered with `embargo` rows dropped on BOTH sides of
    every boundary, per pair. Rows in the embargo are used by nobody."""
    split = pd.Series("embargo", index=matrix.index, dtype=object)
    t_end, v_start, v_end, te_start = (
        pd.Timestamp(config.TRAIN_END),
        pd.Timestamp(config.VAL_START),
        pd.Timestamp(config.VAL_END),
        pd.Timestamp(config.TEST_START),
    )
    for _, g in matrix.groupby("pair", sort=False):
        d = g["date"]
        tr = g.index[d <= t_end]
        va = g.index[(d >= v_start) & (d <= v_end)]
        te = g.index[d >= te_start]
        split.loc[tr[:-embargo]] = "train"  # drop the last `embargo` train rows
        split.loc[va[embargo:-embargo]] = "val"  # drop first and last `embargo` val rows
        split.loc[te[embargo:]] = "test"  # drop the first `embargo` test rows
    return split


def assemble(features: pd.DataFrame, regimes: pd.DataFrame) -> pd.DataFrame:
    """Matrix + label + split in one frame (rows without a label keep NaN)."""
    m = build_matrix(features, regimes)
    m["y"] = build_labels(m)
    m["split"] = assign_splits(m)
    return m


# --------------------------------------------------------------------------------------
# training + baselines
# --------------------------------------------------------------------------------------
def _xy(df: pd.DataFrame, split: str) -> tuple[pd.DataFrame, pd.Series]:
    part = df[(df["split"] == split) & df["y"].notna()]
    return part[FEATURES], part["y"].astype(int)


def fit_forecaster(df: pd.DataFrame) -> tuple[XGBClassifier, dict]:
    """Fit XGBoost on train with early stopping on val. Returns (model, info)."""
    x_tr, y_tr = _xy(df, "train")
    x_va, y_va = _xy(df, "val")
    spw = float((y_tr == 0).sum() / max((y_tr == 1).sum(), 1))  # scale_pos_weight from TRAIN
    model = XGBClassifier(**XGB_PARAMS, scale_pos_weight=spw)
    model.fit(x_tr, y_tr, eval_set=[(x_va, y_va)], verbose=False)
    info = {
        "n_train": int(len(y_tr)),
        "n_val": int(len(y_va)),
        "train_pos_rate": float(y_tr.mean()),
        "scale_pos_weight": spw,
        "best_iteration": int(model.best_iteration),
        "best_val_aucpr": float(model.best_score),
    }
    return model, info


def choose_threshold(
    p_val: np.ndarray, y_val: np.ndarray, target_recall: float = TARGET_RECALL
) -> float:
    """Highest threshold whose recall on VAL is still >= target (max precision s.t. recall constraint)."""
    for thr in np.arange(0.99, 0.0, -0.01):
        if recall_score(y_val, p_val >= thr, zero_division=0) >= target_recall:
            return float(round(thr, 2))
    return 0.0


def fit_calibrator(p_val: np.ndarray, y_val: np.ndarray) -> tuple[float, float]:
    """Platt scaling on VAL: p_cal = sigmoid(a * logit(p) + b). Two parameters, fit once on validation,
    because scale_pos_weight deliberately distorts XGBoost's raw probabilities (recall first) — the
    displayed risk should still mean what it says. Returns (a, b)."""
    z = np.log(np.clip(p_val, 1e-6, 1 - 1e-6) / (1 - np.clip(p_val, 1e-6, 1 - 1e-6))).reshape(-1, 1)
    lr = LogisticRegression(C=1e6, max_iter=1000).fit(z, y_val)
    return float(lr.coef_[0][0]), float(lr.intercept_[0])


def calibrate(p: np.ndarray, a: float, b: float) -> np.ndarray:
    p = np.clip(p, 1e-6, 1 - 1e-6)
    z = a * np.log(p / (1 - p)) + b
    return 1.0 / (1.0 + np.exp(-z))


def fit_baselines(df: pd.DataFrame) -> dict[str, dict]:
    """Base rate, scaled logistic regression, and the one-feature rule (days_in_regime > train median)."""
    x_tr, y_tr = _xy(df, "train")
    scaler = StandardScaler().fit(x_tr)
    logit = LogisticRegression(max_iter=2000, random_state=42).fit(scaler.transform(x_tr), y_tr)
    return {
        "base_rate": {"p": float(y_tr.mean())},
        "logistic": {"scaler": scaler, "model": logit},
        "one_feature": {"median_days": float(x_tr["days_in_regime"].median())},
    }


def predict_baseline(name: str, base: dict, x: pd.DataFrame) -> np.ndarray:
    if name == "base_rate":
        return np.full(len(x), base["p"])
    if name == "logistic":
        return base["model"].predict_proba(base["scaler"].transform(x))[:, 1]
    if name == "one_feature":
        return (x["days_in_regime"] > base["median_days"]).astype(float).to_numpy()
    raise KeyError(name)


def metrics(y: np.ndarray, p: np.ndarray, thr: float) -> dict[str, float]:
    """PR-AUC, precision & recall at `thr`, Brier. Never accuracy."""
    return {
        "pr_auc": float(average_precision_score(y, p)),
        "precision": float(precision_score(y, p >= thr, zero_division=0)),
        "recall": float(recall_score(y, p >= thr, zero_division=0)),
        "brier": float(brier_score_loss(y, np.clip(p, 0, 1))),
        "n": int(len(y)),
        "pos_rate": float(np.mean(y)),
    }


# --------------------------------------------------------------------------------------
# SHAP drivers
# --------------------------------------------------------------------------------------
def shap_values(model: XGBClassifier, x: pd.DataFrame) -> np.ndarray:
    import shap

    explainer = shap.TreeExplainer(model)
    vals = explainer.shap_values(x)
    return np.asarray(vals if not isinstance(vals, list) else vals[-1])


def top_drivers(shap_vals: np.ndarray, k: int = 3) -> list[list[str]]:
    """Per row, the k feature names with the largest |SHAP| (list of k strings)."""
    order = np.argsort(-np.abs(shap_vals), axis=1)[:, :k]
    names = np.array(FEATURES)
    return [[str(n) for n in names[row]] for row in order]


# --------------------------------------------------------------------------------------
# persistence + scoring (used by the daily pipeline)
# --------------------------------------------------------------------------------------
def model_path(version: str = FORECASTER_VERSION, models_dir: Path = config.MODELS_DIR) -> Path:
    return models_dir / f"forecaster_v{version}.json"


def meta_path(version: str = FORECASTER_VERSION, models_dir: Path = config.MODELS_DIR) -> Path:
    return models_dir / f"forecaster_v{version}.meta.json"


def save_model(
    model: XGBClassifier,
    meta: dict,
    version: str = FORECASTER_VERSION,
    models_dir: Path = config.MODELS_DIR,
) -> Path:
    models_dir.mkdir(parents=True, exist_ok=True)
    model.save_model(model_path(version, models_dir))  # xgboost native json
    meta_path(version, models_dir).write_text(json.dumps(meta, indent=2, default=str))
    return model_path(version, models_dir)


def load_model(
    version: str | None = None, models_dir: Path = config.MODELS_DIR
) -> tuple[XGBClassifier, dict]:
    version = version or hm.read_manifest(models_dir).get("forecaster", {}).get(
        "version", FORECASTER_VERSION
    )
    model = XGBClassifier()
    model.load_model(model_path(version, models_dir))
    meta = json.loads(meta_path(version, models_dir).read_text())
    return model, meta


def score(model: XGBClassifier, matrix: pd.DataFrame, meta: dict | None = None) -> pd.DataFrame:
    """change_risk_5d (calibrated) + top_drivers for every row of the pooled matrix (causal inputs)."""
    x = matrix[FEATURES]
    out = matrix[["date", "pair"]].copy()
    raw = model.predict_proba(x)[:, 1].astype(float)
    cal = (meta or {}).get("calibration")
    out["change_risk_5d"] = calibrate(raw, cal["a"], cal["b"]) if cal else raw
    out["top_drivers"] = top_drivers(shap_values(model, x))
    return out


# --------------------------------------------------------------------------------------
# evaluation report
# --------------------------------------------------------------------------------------
def _md(df: pd.DataFrame, fmt: str = "{:.3f}") -> str:
    cols = [str(c) for c in df.columns]
    out = ["| " + " | ".join(cols) + " |", "|" + "|".join(["---"] * len(cols)) + "|"]
    for _, r in df.iterrows():
        out.append(
            "| " + " | ".join(fmt.format(v) if isinstance(v, float) else str(v) for v in r) + " |"
        )
    return "\n".join(out)


def _plots(
    y_te: np.ndarray, p_te: np.ndarray, model: XGBClassifier, x_te: pd.DataFrame, reports_dir: Path
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import shap

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
        }
    )
    frac_pos, mean_pred = calibration_curve(y_te, p_te, n_bins=10, strategy="quantile")
    fig, ax = plt.subplots(figsize=(5.2, 4.6))
    ax.plot([0, 1], [0, 1], ls="--", color="#8A94A6", lw=1, label="perfect")
    ax.plot(mean_pred, frac_pos, marker="o", color="#60A5FA", label="XGBoost (test)")
    ax.set_xlabel("predicted 5-day change risk")
    ax.set_ylabel("observed change frequency")
    ax.set_title("Calibration — test set (2019+), 10 quantile bins", loc="left", fontsize=10)
    ax.grid(alpha=0.3)
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(reports_dir / "forecaster_calibration.png", dpi=110)
    plt.close(fig)

    sample = x_te.sample(min(2000, len(x_te)), random_state=0)
    sv = shap.TreeExplainer(model).shap_values(sample)
    plt.figure(figsize=(7.5, 5.2))
    shap.summary_plot(
        np.asarray(sv), sample, feature_names=FEATURES, show=False, max_display=15, color_bar=False
    )
    plt.title("SHAP beeswarm — test-set sample", loc="left", fontsize=10)
    plt.tight_layout()
    plt.savefig(reports_dir / "forecaster_shap.png", dpi=110, facecolor="#0B0F17")
    plt.close("all")


def train_and_report(
    reports_dir: Path = config.REPORTS_DIR, models_dir: Path = config.MODELS_DIR
) -> dict:
    """Train, choose the threshold on val, score the test set ONCE, write report + pngs + model."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    feats = pd.read_parquet(config.FEATURES_PATH)
    regs = pd.read_parquet(config.REGIMES_PATH)
    df = assemble(feats, regs)
    model, info = fit_forecaster(df)
    x_va, y_va = _xy(df, "val")
    p_va_raw = model.predict_proba(x_va)[:, 1]
    a, b = fit_calibrator(p_va_raw, y_va.to_numpy())
    p_va = calibrate(p_va_raw, a, b)
    thr = choose_threshold(p_va, y_va.to_numpy())
    bases = fit_baselines(df)

    x_te, y_te = _xy(df, "test")
    p_te_raw = model.predict_proba(x_te)[:, 1]
    p_te = calibrate(p_te_raw, a, b)
    rows = [
        {
            "model": "XGBoost (ours, calibrated)",
            "threshold": thr,
            **metrics(y_te.to_numpy(), p_te, thr),
        }
    ]
    raw_row = {
        "model": "XGBoost (raw, uncalibrated)",
        "threshold": choose_threshold(p_va_raw, y_va.to_numpy()),
        **metrics(y_te.to_numpy(), p_te_raw, choose_threshold(p_va_raw, y_va.to_numpy())),
    }
    for name in ["base_rate", "logistic", "one_feature"]:
        pb_va = predict_baseline(name, bases[name], x_va)
        thr_b = 0.5 if name == "one_feature" else choose_threshold(pb_va, y_va.to_numpy())
        pb_te = predict_baseline(name, bases[name], x_te)
        rows.append({"model": name, "threshold": thr_b, **metrics(y_te.to_numpy(), pb_te, thr_b)})
    board = pd.DataFrame([*rows, raw_row])
    val_m = metrics(y_va.to_numpy(), p_va, thr)
    _plots(y_te.to_numpy(), p_te, model, x_te, reports_dir)

    meta = {
        "version": FORECASTER_VERSION,
        "features": FEATURES,
        "horizon": HORIZON,
        "threshold": thr,
        "calibration": {"a": a, "b": b, "method": "Platt scaling fit on validation"},
        "trained_utc": datetime.now().strftime("%Y-%m-%dT%H:%MZ"),
        "params": {k: v for k, v in XGB_PARAMS.items()},
        **info,
        "val_metrics": val_m,
        "test_scoreboard": [*rows, raw_row],
    }
    save_model(model, meta, models_dir=models_dir)
    hm.write_manifest(
        models_dir, forecaster={"version": FORECASTER_VERSION, "trained_utc": meta["trained_utc"]}
    )

    ours, logit = rows[0], rows[2]
    lift = ours["pr_auc"] - logit["pr_auc"]
    L = [
        "# Forecaster evaluation — 5-day regime-change risk\n",
        f"_Generated {datetime.now():%Y-%m-%d %H:%M}. Pooled across pairs. Train ≤ {config.TRAIN_END} ({info['n_train']} rows), val {config.VAL_START[:4]}–{config.VAL_END[:4]} ({info['n_val']} rows), test {config.TEST_START[:4]}+ ({len(y_te)} rows); 5-trading-day embargo on both sides of every boundary. The test set was scored ONCE for this report and its numbers are frozen._\n",
        "## Setup\n",
        f"- Label: regime label differs at any of t+1..t+5 (train positive rate {info['train_pos_rate']:.1%}).\n- Features ({len(FEATURES)}): {', '.join(FEATURES)} — all causal; HMM-derived ones from FILTERED outputs (asserted by a truncation-invariance test).\n- Model: XGBClassifier, fixed hyper-parameters (no grid search — deliberate restraint), scale_pos_weight {info['scale_pos_weight']:.2f} from train, early stopping on val at iteration {info['best_iteration']} (val PR-AUC {info['best_val_aucpr']:.3f}).\n- Probabilities: Platt-recalibrated on VAL (a={a:.2f}, b={b:.2f}) because scale_pos_weight distorts raw XGBoost probabilities; raw numbers are shown in the scoreboard for honesty.\n- Threshold {thr:.2f} chosen on VAL to reach recall ≥ {TARGET_RECALL:.0%} on transitions (val recall {val_m['recall']:.2f}, precision {val_m['precision']:.2f}). Early-warning economics: a false alarm costs a look; a missed storm costs the reason the tool exists — so we buy recall and pay in precision, and we say so.\n",
        "## Scoreboard — test set (2019+), scored once\n",
        f"Never accuracy: with a test positive rate of {ours['pos_rate']:.0%}, 'never changes' would score {1 - ours['pos_rate']:.0%} accuracy and mean nothing.\n",
        _md(board) + "\n",
        "Baselines: base rate = constant train positive rate; logistic = LogisticRegression on the same standardised features; one_feature = 'predict change if days_in_regime > train median' (a binary rule, so its PR-AUC is that of a step function).\n",
        "## Calibration\n",
        f"Brier {ours['brier']:.4f} vs base-rate Brier {rows[1]['brier']:.4f}. The curve below compares predicted risk with observed change frequency in 10 quantile bins on the test set.\n",
        "![calibration](forecaster_calibration.png)\n",
        "## Drivers (SHAP)\n",
        "![shap](forecaster_shap.png)\n",
        "## Honest interpretation\n",
        (
            f"XGBoost reaches PR-AUC {ours['pr_auc']:.3f} on the test set against {logit['pr_auc']:.3f} for the logistic baseline and {rows[1]['pr_auc']:.3f} for the base rate — a lift of {lift:+.3f} over logistic. "
            + (
                "That is a thin margin: the non-linear model earns its place mainly through calibration and the SHAP explanations, not through raw ranking power. "
                if lift < 0.03
                else "That is a clear margin over a linear model on the same features. "
            )
            + f"At the chosen threshold it catches {ours['recall']:.0%} of transitions with precision {ours['precision']:.0%}. "
            + f"Calibration: Brier {ours['brier']:.4f} calibrated vs {raw_row['brier']:.4f} raw vs {logit['brier']:.4f} logistic — "
            + (
                "the recalibrated probabilities are at least as well calibrated as the linear model's. "
                if ours["brier"] <= logit["brier"] + 1e-4
                else "the linear model is still slightly better calibrated; XGBoost wins on ranking, not on probability quality. "
            )
            + "Regime transitions in a sticky HMM are intrinsically hard to time (the label flips on the HMM's own filtered decision), so no forecaster here should be read as a market call — it is a change-risk gauge.\n"
        ),
        "\n_Educational tool. Not investment advice._\n",
    ]
    (reports_dir / "forecaster_eval.md").write_text("\n".join(L))
    return meta


def main() -> None:
    parser = argparse.ArgumentParser(description="FX Regime Radar — regime-change forecaster")
    parser.add_argument(
        "--train",
        action="store_true",
        help="train + evaluate + save (default: score with the saved model)",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if args.train:
        meta = train_and_report()
        print(
            json.dumps(
                {
                    k: meta[k]
                    for k in ["best_iteration", "best_val_aucpr", "threshold", "val_metrics"]
                },
                indent=2,
                default=str,
            )
        )
        print(pd.DataFrame(meta["test_scoreboard"]).round(3).to_string(index=False))
        print(f"\nwrote {config.REPORTS_DIR / 'forecaster_eval.md'} and {model_path()}")
    else:
        model, meta = load_model()
        df = build_matrix(
            pd.read_parquet(config.FEATURES_PATH), pd.read_parquet(config.REGIMES_PATH)
        )
        out = score(model, df, meta)
        print(out.groupby("pair").tail(1).to_string(index=False))


if __name__ == "__main__":
    main()
