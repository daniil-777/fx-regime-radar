"""Challenger forecaster (phase 23): the phase-07 XGBoost recipe on features + features_ext.

Same question ("does the filtered regime label change within the next 5 trading days?"), same
labels, same time-ordered splits and 5-day embargo, same hyper-parameters, same Platt
recalibration and threshold rule (TARGET_RECALL on validation), same metrics — PR-AUC, Brier,
precision/recall on transitions, never accuracy (CLAUDE.md rules 2, 3). The only difference is
the design matrix: the champion's FEATURES plus the calendar / cross-asset / mood / Yang-Zhang
columns from `data/features_ext.parquet`.

The challenger never replaces the champion by itself. It writes its own scores
(`change_risk_5d_ch`, `top_drivers_ch`) and ledger rows with model_version "challenger=1.0.0";
promotion is a deliberate refit-path act once it has beaten the champion on the live ledger
(see PROMOTION_CRITERIA). The Rust wall is untouched: this model is Python-only research.
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from xgboost import XGBClassifier

from fxradar import config, features_ext, forecaster

log = logging.getLogger(__name__)

CHALLENGER_VERSION = "1.0.0"
MODEL_VERSION_TAG = f"challenger={CHALLENGER_VERSION}"
FEATURES: list[str] = [*forecaster.FEATURES, *features_ext.EXT_FEATURES]
PROMOTION_CRITERIA = (
    "Promote only if the challenger's live PR-AUC on the ledger (matured rows, same outcomes "
    "as the champion) exceeds the champion's over >= 60 matured days AND its Brier score is not "
    "worse; promotion is a deliberate refit-path act (re-export, new model_version, CHANGELOG), "
    "never automatic. The frozen test scoreboard below is context, not the promotion trigger."
)


def model_path(version: str = CHALLENGER_VERSION, models_dir: Path = config.MODELS_DIR) -> Path:
    return models_dir / f"forecaster_challenger_v{version}.json"


def meta_path(version: str = CHALLENGER_VERSION, models_dir: Path = config.MODELS_DIR) -> Path:
    return models_dir / f"forecaster_challenger_v{version}.meta.json"


# --------------------------------------------------------------------------------------
# matrix
# --------------------------------------------------------------------------------------
def build_matrix(features: pd.DataFrame, regimes: pd.DataFrame, ext: pd.DataFrame) -> pd.DataFrame:
    """Champion matrix (date, pair, regime + forecaster.FEATURES) left-joined with features_ext on
    (date, pair). Rows missing in features_ext keep NaN (XGBoost handles it; nothing is filled)."""
    m = forecaster.build_matrix(features, regimes)
    m = m.merge(ext[["date", "pair", *features_ext.EXT_FEATURES]], on=["date", "pair"], how="left")
    return m[["date", "pair", "regime", *FEATURES]]


def assemble(features: pd.DataFrame, regimes: pd.DataFrame, ext: pd.DataFrame) -> pd.DataFrame:
    """Matrix + label + split (reusing the champion's label and embargoed split rules)."""
    m = build_matrix(features, regimes, ext)
    m["y"] = forecaster.build_labels(m, forecaster.HORIZON)
    m["split"] = forecaster.assign_splits(m)
    return m


def _xy(df: pd.DataFrame, split: str, cols: list[str]) -> tuple[pd.DataFrame, pd.Series]:
    part = df[(df["split"] == split) & df["y"].notna()]
    return part[cols], part["y"].astype(int)


# --------------------------------------------------------------------------------------
# training
# --------------------------------------------------------------------------------------
def fit_challenger(df: pd.DataFrame) -> tuple[XGBClassifier, dict]:
    """Same recipe as forecaster.fit_forecaster (XGB_PARAMS, scale_pos_weight from train, early
    stopping on val) on the extended column list."""
    x_tr, y_tr = _xy(df, "train", FEATURES)
    x_va, y_va = _xy(df, "val", FEATURES)
    spw = float((y_tr == 0).sum() / max((y_tr == 1).sum(), 1))
    model = XGBClassifier(**forecaster.XGB_PARAMS, scale_pos_weight=spw)
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


def shap_top_drivers(model: XGBClassifier, x: pd.DataFrame, k: int = 3) -> list[list[str]]:
    """Per row, the k feature names with the largest |SHAP| (challenger feature names)."""
    import shap

    vals = shap.TreeExplainer(model).shap_values(x)
    vals = np.asarray(vals if not isinstance(vals, list) else vals[-1])
    order = np.argsort(-np.abs(vals), axis=1)[:, :k]
    names = np.array(FEATURES)
    return [[str(n) for n in names[row]] for row in order]


def score(model: XGBClassifier, matrix: pd.DataFrame, meta: dict | None = None) -> pd.DataFrame:
    """(date, pair, change_risk_5d calibrated, top_drivers) for every row of the pooled matrix."""
    x = matrix[FEATURES]
    out = matrix[["date", "pair"]].copy()
    raw = model.predict_proba(x)[:, 1].astype(float)
    cal = (meta or {}).get("calibration")
    out["change_risk_5d"] = forecaster.calibrate(raw, cal["a"], cal["b"]) if cal else raw
    out["top_drivers"] = shap_top_drivers(model, x)
    return out


def save_model(model: XGBClassifier, meta: dict, models_dir: Path = config.MODELS_DIR) -> Path:
    models_dir.mkdir(parents=True, exist_ok=True)
    model.save_model(model_path(models_dir=models_dir))
    meta_path(models_dir=models_dir).write_text(json.dumps(meta, indent=2, default=str))
    return model_path(models_dir=models_dir)


def load_model(models_dir: Path = config.MODELS_DIR) -> tuple[XGBClassifier, dict]:
    model = XGBClassifier()
    model.load_model(model_path(models_dir=models_dir))
    return model, json.loads(meta_path(models_dir=models_dir).read_text())


# --------------------------------------------------------------------------------------
# train + frozen scoreboard
# --------------------------------------------------------------------------------------
def train(reports_dir: Path = config.REPORTS_DIR, models_dir: Path = config.MODELS_DIR) -> dict:
    """Train on train, calibrate + threshold on val, score the test set ONCE (frozen), write the
    champion-vs-challenger scoreboard and the model + meta."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    feats = pd.read_parquet(config.FEATURES_PATH)
    regs = pd.read_parquet(config.REGIMES_PATH)
    ext = pd.read_parquet(features_ext.FEATURES_EXT_PATH)
    df = assemble(feats, regs, ext)

    model, info = fit_challenger(df)
    x_va, y_va = _xy(df, "val", FEATURES)
    p_va_raw = model.predict_proba(x_va)[:, 1]
    a, b = forecaster.fit_calibrator(p_va_raw, y_va.to_numpy())
    p_va = forecaster.calibrate(p_va_raw, a, b)
    thr = forecaster.choose_threshold(p_va, y_va.to_numpy())
    x_te, y_te = _xy(df, "test", FEATURES)
    p_te = forecaster.calibrate(model.predict_proba(x_te)[:, 1], a, b)

    # champion on the SAME rows with its saved model + its own calibration/threshold
    champ, champ_meta = forecaster.load_model(models_dir=models_dir)
    c_cal, c_thr = champ_meta["calibration"], float(champ_meta["threshold"])
    c_va = forecaster.calibrate(
        champ.predict_proba(x_va[forecaster.FEATURES])[:, 1], c_cal["a"], c_cal["b"]
    )
    c_te = forecaster.calibrate(
        champ.predict_proba(x_te[forecaster.FEATURES])[:, 1], c_cal["a"], c_cal["b"]
    )
    base_p = float(_xy(df, "train", FEATURES)[1].mean())

    def row(name: str, split: str, y: np.ndarray, p: np.ndarray, t: float) -> dict:
        return {"model": name, "split": split, "threshold": t, **forecaster.metrics(y, p, t)}

    board = [
        row(f"champion v{champ_meta['version']}", "val", y_va.to_numpy(), c_va, c_thr),
        row(f"challenger v{CHALLENGER_VERSION}", "val", y_va.to_numpy(), p_va, thr),
        row("base_rate", "val", y_va.to_numpy(), np.full(len(y_va), base_p), 0.5),
        row(f"champion v{champ_meta['version']}", "test", y_te.to_numpy(), c_te, c_thr),
        row(f"challenger v{CHALLENGER_VERSION}", "test", y_te.to_numpy(), p_te, thr),
        row("base_rate", "test", y_te.to_numpy(), np.full(len(y_te), base_p), 0.5),
    ]
    gain = pd.DataFrame({"feature": FEATURES, "gain": model.feature_importances_}).sort_values(
        "gain", ascending=False
    )
    meta = {
        "version": CHALLENGER_VERSION,
        "model_version_tag": MODEL_VERSION_TAG,
        "champion_version": champ_meta["version"],
        "features": FEATURES,
        "n_features": len(FEATURES),
        "ext_features": features_ext.EXT_FEATURES,
        "horizon": forecaster.HORIZON,
        "threshold": thr,
        "target_recall": forecaster.TARGET_RECALL,
        "calibration": {"a": a, "b": b, "method": "Platt scaling fit on validation"},
        "trained_utc": datetime.now().strftime("%Y-%m-%dT%H:%MZ"),
        "params": dict(forecaster.XGB_PARAMS),
        **info,
        "scoreboard": board,
        "frozen_test": {
            "scored_once_utc": datetime.now().strftime("%Y-%m-%dT%H:%MZ"),
            "n": int(len(y_te)),
        },
        "top_gain_features": gain.head(15).to_dict(orient="records"),
        "promotion_criteria": PROMOTION_CRITERIA,
    }
    save_model(model, meta, models_dir)
    _report(meta, board, gain, info, reports_dir)
    return meta


def _md(df: pd.DataFrame) -> str:
    cols = [str(c) for c in df.columns]
    out = ["| " + " | ".join(cols) + " |", "|" + "|".join(["---"] * len(cols)) + "|"]
    for r in df.itertuples(index=False):
        out.append(
            "| " + " | ".join(f"{v:.3f}" if isinstance(v, float) else str(v) for v in r) + " |"
        )
    return "\n".join(out)


def _report(
    meta: dict, board: list[dict], gain: pd.DataFrame, info: dict, reports_dir: Path
) -> None:
    b = pd.DataFrame(board)
    ch_te = b[(b["split"] == "test") & b["model"].str.startswith("challenger")].iloc[0]
    cp_te = b[(b["split"] == "test") & b["model"].str.startswith("champion")].iloc[0]
    d_auc, d_brier = ch_te["pr_auc"] - cp_te["pr_auc"], ch_te["brier"] - cp_te["brier"]
    ext_in_top = gain.head(15)["feature"].isin(features_ext.EXT_FEATURES).sum()
    text = [
        "# Challenger evaluation — champion vs challenger (phase 23)\n",
        f"_Generated {datetime.now():%Y-%m-%d %H:%M}. Same labels, splits (train <= {config.TRAIN_END}, val {config.VAL_START[:4]}–{config.VAL_END[:4]}, test {config.TEST_START[:4]}+), 5-day embargo, XGB params, Platt calibration on val and threshold rule (recall >= {forecaster.TARGET_RECALL:.0%} on val) as the champion. The only change is the matrix: {len(forecaster.FEATURES)} champion features + {len(features_ext.EXT_FEATURES)} extended (calendar countdowns, lagged cross-asset / EPU / COT, Yang-Zhang). The test set was scored ONCE for this report and is frozen._\n",
        "## Scoreboard (never accuracy)\n",
        _md(
            b[
                [
                    "model",
                    "split",
                    "threshold",
                    "pr_auc",
                    "precision",
                    "recall",
                    "brier",
                    "n",
                    "pos_rate",
                ]
            ]
        )
        + "\n",
        f"Train rows {info['n_train']}, val rows {info['n_val']}; early stopping at iteration {info['best_iteration']} (val PR-AUC {info['best_val_aucpr']:.3f}); threshold {meta['threshold']:.2f}.\n",
        "## Where the extended features rank (XGBoost gain, top 15)\n",
        _md(gain.head(15).reset_index(drop=True)) + "\n",
        f"{ext_in_top} of the top-15 gain features come from features_ext.\n",
        "## Honest reading\n",
        (
            f"On the frozen test set the challenger's PR-AUC is {ch_te['pr_auc']:.3f} vs the champion's {cp_te['pr_auc']:.3f} ({d_auc:+.3f}); Brier {ch_te['brier']:.4f} vs {cp_te['brier']:.4f} ({d_brier:+.4f}, lower is better). "
            + (
                "That is within the noise of one test window — conditioning on the calendar and context does not obviously beat the frozen champion here, which is itself a finding: scheduled-event countdowns move volatility, not necessarily the HMM's regime label. "
                if abs(d_auc) < 0.02
                else (
                    "The challenger ranks transitions better on this window. "
                    if d_auc > 0
                    else "The champion ranks transitions better on this window; more features did not help out of sample. "
                )
            )
            + "Either way the decision is not taken here: the two models now race on the live ledger.\n"
        ),
        "## Promotion criteria\n",
        PROMOTION_CRITERIA + "\n",
        "\n_Educational tool. Not investment advice._\n",
    ]
    (reports_dir / "challenger_eval.md").write_text("\n".join(text))


# --------------------------------------------------------------------------------------
# daily stage
# --------------------------------------------------------------------------------------
def stage(ctx: dict, models_dir: Path = config.MODELS_DIR) -> None:
    """run_daily stage (after 'forecaster'): score the challenger, merge `change_risk_5d_ch` /
    `top_drivers_ch` onto ctx['regimes'], expose ctx['challenger_scores'] for the ledger."""
    model, meta = load_model(models_dir)
    ext = ctx.get("features_ext")
    if ext is None:
        ext = pd.read_parquet(features_ext.FEATURES_EXT_PATH)
    matrix = build_matrix(ctx["features"], ctx["regimes"], ext)
    scored = score(model, matrix, meta)
    merged = scored.rename(
        columns={"change_risk_5d": "change_risk_5d_ch", "top_drivers": "top_drivers_ch"}
    )
    ctx["regimes"] = ctx["regimes"].merge(merged, on=["date", "pair"], how="left")
    ctx.setdefault("model_versions", {})["challenger"] = meta["version"]
    ctx["challenger_meta"] = meta
    ctx["challenger_scores"] = scored[["date", "pair", "change_risk_5d"]].assign(
        model_version=MODEL_VERSION_TAG
    )
    latest = ctx["regimes"].sort_values("date").groupby("pair").tail(1)
    log.info(
        "challenger: %s",
        ", ".join(
            f"{r.pair} risk_ch={r.change_risk_5d_ch:.2f} {r.top_drivers_ch}"
            for r in latest.itertuples()
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="FX Regime Radar — challenger forecaster")
    parser.add_argument("--train", action="store_true", help="train + frozen scoreboard + save")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if args.train:
        meta = train()
        print(pd.DataFrame(meta["scoreboard"]).round(3).to_string(index=False))
        print(f"\nwrote {config.REPORTS_DIR / 'challenger_eval.md'} and {model_path()}")
    else:
        ctx = {
            "features": pd.read_parquet(config.FEATURES_PATH),
            "regimes": pd.read_parquet(config.REGIMES_PATH),
        }
        stage(ctx)
        print(
            ctx["regimes"]
            .sort_values("date")
            .groupby("pair")
            .tail(1)[
                ["date", "pair", "regime", "change_risk_5d", "change_risk_5d_ch", "top_drivers_ch"]
            ]
            .to_string(index=False)
        )


if __name__ == "__main__":
    main()
