"""Export the versioned model bundle — the ONLY artifact that crosses the wall (CLAUDE.md rule 11).

models/bundle_v{semver}/ contains language-neutral files only (json, onnx, yaml, parquet — never
pickle): per-pair HMM parameters with PRECOMPUTED precision matrices and log-determinants (Rust
does no decompositions), the forecaster and siren as ONNX with sidecar json (scaler, calibration,
feature order), a feature spec, 300 golden vectors with raw price windows and Python's exact
outputs, and a manifest with SHA-256 hashes and parity diffs. Rust replays the goldens at start-up
and refuses to serve on any mismatch.
"""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import onnxruntime as ort
import pandas as pd
import yaml

import fxradar
from fxradar import config, features, forecaster, siren
from fxradar import hmm_model as hm

log = logging.getLogger(__name__)

BUNDLE_VERSION = "1.4.0"
WINDOW = 600  # trading days of raw prices per pair in each golden vector (>= longest regime run + warm-up)
N_GOLDENS = 300
PARITY_TOL = 1e-6


def bundle_dir(version: str = BUNDLE_VERSION, models_dir: Path = config.MODELS_DIR) -> Path:
    return models_dir / f"bundle_v{version}"


# --------------------------------------------------------------------------------------
# HMM json (means, covariances, precomputed precision + logdet, transitions, scaler, mapping)
# --------------------------------------------------------------------------------------
def hmm_to_json(bundle: hm.HMMBundle) -> dict:
    m = bundle.model
    precisions, logdets = [], []
    for cov in m.covars_:
        chol = np.linalg.cholesky(cov)  # cov = L L^T
        precisions.append(np.linalg.inv(cov).tolist())
        logdets.append(float(2.0 * np.log(np.diag(chol)).sum()))
    return {
        "pair": bundle.pair,
        "version": bundle.version,
        "features": list(bundle.features),
        "n_states": int(m.n_components),
        "means": m.means_.tolist(),
        "covariances": m.covars_.tolist(),
        "precisions": precisions,
        "log_dets": logdets,
        "transmat": m.transmat_.tolist(),
        "startprob": m.startprob_.tolist(),
        "scaler_mean": bundle.scaler.mean_.tolist(),
        "scaler_scale": bundle.scaler.scale_.tolist(),
        "state_names": [bundle.mapping[i] for i in range(m.n_components)],
        "train_end": bundle.train_end,
    }


# --------------------------------------------------------------------------------------
# ONNX conversions with parity checks
# --------------------------------------------------------------------------------------
def export_forecaster(out: Path, x_val: pd.DataFrame) -> dict:
    """forecaster.onnx + forecaster.json; returns parity info (max |onnx - xgboost| on val)."""
    from onnxmltools.convert import convert_xgboost
    from onnxmltools.convert.common.data_types import FloatTensorType

    model, meta = forecaster.load_model()
    model.get_booster().feature_names = None  # onnxmltools wants f0..fN names
    onx = convert_xgboost(
        model,
        initial_types=[("input", FloatTensorType([None, len(forecaster.FEATURES)]))],
        target_opset=15,
    )  # outputs: label (int64), probabilities (float [n, 2]) — a plain tensor, no ZipMap
    (out / "forecaster.onnx").write_bytes(onx.SerializeToString())
    ref_model, _ = forecaster.load_model()
    p_ref = ref_model.predict_proba(x_val[forecaster.FEATURES])[:, 1]
    sess = ort.InferenceSession(str(out / "forecaster.onnx"), providers=["CPUExecutionProvider"])
    outs = sess.run(None, {"input": x_val[forecaster.FEATURES].to_numpy(np.float32)})
    p_onnx = np.array([d[1] for d in outs[1]]) if isinstance(outs[1], list) else outs[1][:, 1]
    diff = float(np.abs(p_onnx - p_ref).max())
    if diff > PARITY_TOL:
        raise AssertionError(f"forecaster ONNX parity {diff:.2e} > {PARITY_TOL}")
    sidecar = {
        "version": meta["version"],
        "features": forecaster.FEATURES,
        "onnx_input": "input",
        "dtype": "float32",
        "onnx_output_probabilities": sess.get_outputs()[1].name,
        "calibration": meta["calibration"],
        "threshold": meta["threshold"],
        "horizon": forecaster.HORIZON,
    }
    (out / "forecaster.json").write_text(json.dumps(sidecar, indent=2))
    return {"forecaster_onnx_max_abs_diff": diff, "n_checked": int(len(p_ref))}


def export_siren(out: Path, x_scaled: np.ndarray) -> dict:
    """siren.onnx (float64 in/out, output reshaped to (n, 9)) + siren.json; returns parity info."""
    import onnx
    from onnx import TensorProto, helper
    from skl2onnx import convert_sklearn
    from skl2onnx.common.data_types import DoubleTensorType

    b = siren.load_bundle()
    n_feat = len(siren.SIREN_FEATURES)
    onx = convert_sklearn(
        b["model"], initial_types=[("input", DoubleTensorType([None, n_feat]))], target_opset=15
    )
    # skl2onnx flattens the multi-output MLPRegressor to (n*9, 1); append a Reshape to (n, 9)
    g = onx.graph
    old = g.output[0].name
    for node in g.node:
        for i, o in enumerate(node.output):
            if o == old:
                node.output[i] = "raw_flat"
    g.initializer.append(
        helper.make_tensor("siren_out_shape", TensorProto.INT64, [2], [-1, n_feat])
    )
    g.node.append(
        helper.make_node("Reshape", ["raw_flat", "siren_out_shape"], ["output"], name="reshape_out")
    )
    g.output[0].CopyFrom(
        helper.make_tensor_value_info("output", TensorProto.DOUBLE, [None, n_feat])
    )
    onnx.checker.check_model(onx)
    (out / "siren.onnx").write_bytes(onx.SerializeToString())
    sess = ort.InferenceSession(str(out / "siren.onnx"), providers=["CPUExecutionProvider"])
    r_onnx = sess.run(None, {"input": x_scaled.astype(np.float64)})[0]
    r_ref = b["model"].predict(x_scaled)
    diff = float(np.abs(r_onnx - r_ref).max())
    if diff > PARITY_TOL:
        raise AssertionError(f"siren ONNX parity {diff:.2e} > {PARITY_TOL}")
    sidecar = {
        "version": b["version"],
        "features": siren.SIREN_FEATURES,
        "onnx_input": "input",
        "onnx_output": "output",
        "dtype": "float64",
        "scaler_mean": b["scaler"].mean_.tolist(),
        "scaler_scale": b["scaler"].scale_.tolist(),
        "train_scores_sorted": [float(v) for v in b["train_scores"]],
        "hidden_layer_sizes": list(siren.HIDDEN),
    }
    (out / "siren.json").write_text(json.dumps(sidecar))
    return {"siren_onnx_max_abs_diff": diff, "n_checked": int(len(r_ref))}


# --------------------------------------------------------------------------------------
# feature spec
# --------------------------------------------------------------------------------------
def feature_spec() -> dict:
    return {
        "version": BUNDLE_VERSION,
        "pairs": config.PAIRS,
        "usd_base_pairs": sorted(config.USD_BASE_PAIRS),
        "annualize": "sqrt(252)",
        "std_ddof": 1,
        "warmup_rows": features.WARMUP_ROWS,
        "golden_window_rows": WINDOW,
        "base_features": [
            {"name": "ret_1d", "formula": "log(close_t / close_{t-1})"},
            {
                "name": "vol_20",
                "window": 20,
                "formula": "std(ret_1d over last 20 rows, ddof=1) * sqrt(252)",
            },
            {
                "name": "vol_60",
                "window": 60,
                "formula": "std(ret_1d over last 60 rows, ddof=1) * sqrt(252)",
            },
            {
                "name": "vol_ratio",
                "window": 5,
                "formula": "(std(ret_1d over last 5 rows, ddof=1) * sqrt(252)) / vol_60",
            },
            {"name": "mom_20", "window": 20, "formula": "close_t / close_{t-20} - 1"},
            {
                "name": "rng_hl",
                "window": 10,
                "formula": "mean over last 10 rows of (high - low) / close",
            },
            {
                "name": "corr_20",
                "window": 20,
                "formula": "mean over the two other pairs of corr(ret_a, ret_b) on the last 20 dates BOTH pairs traded (USD-base pairs sign-flipped first), as-of aligned backward to the pair's own dates; NaN if undefined",
            },
            {"name": "ret_5d_abs", "window": 5, "formula": "abs(close_t / close_{t-5} - 1)"},
        ],
        "hmm": {
            "features": hm.HMM_FEATURES,
            "n_states": hm.N_STATES,
            "regimes": hm.REGIMES,
            "outputs": [
                "regime",
                "regime_prob",
                "hmm_entropy (nats)",
                "days_in_regime (run length incl. today)",
                "vol_trend = sign(vol_20_t - vol_20_{t-10}) (0 if undefined)",
            ],
            "filter": "forward algorithm from window start with startprob, logsumexp-normalised each step",
        },
        "forecaster": {
            "features": forecaster.FEATURES,
            "one_hot_base": {"regime": "calm", "pair": "EURUSD"},
            "output": "change_risk_5d = platt(onnx_probability) with sidecar a, b",
        },
        "siren": {
            "features": siren.SIREN_FEATURES,
            "output": "anomaly_score = mean((onnx(x_scaled) - x_scaled)^2); anomaly_pct = searchsorted(train_scores_sorted, score, side=right) / n * 100",
        },
    }


# --------------------------------------------------------------------------------------
# golden vectors
# --------------------------------------------------------------------------------------
def _sample_goldens(regimes: pd.DataFrame, n: int, seed: int = 0) -> pd.DataFrame:
    """~n rows stratified over pair x year x regime, always including 2015-01-15/16 USDCHF."""
    rng = np.random.default_rng(seed)
    r = regimes.copy()
    r["year"] = r["date"].dt.year
    per_pair = n // len(config.PAIRS) + 2  # slack: duplicates are dropped below
    picks = []
    for _pair, g in r.groupby("pair"):
        g = g[g.groupby("pair").cumcount() >= WINDOW]  # enough history for the raw window
        groups = list(g.groupby(["year", "regime"]).groups.values())
        # round-robin one row per (year, regime) group until per_pair reached
        chosen: list = []
        i = 0
        while len(chosen) < per_pair and groups:
            idx = groups[i % len(groups)]
            chosen.append(rng.choice(idx))
            i += 1
            if i > 10 * per_pair:
                break
        picks.extend(sorted(set(chosen)))
    keep = r.loc[picks, ["date", "pair"]]
    snb = r[
        (r["pair"] == "USDCHF") & (r["date"].isin(pd.to_datetime(["2015-01-15", "2015-01-16"])))
    ][["date", "pair"]]
    return (
        pd.concat([keep, snb])
        .drop_duplicates()
        .sort_values(["pair", "date"])
        .reset_index(drop=True)
    )


def _window(prices: pd.DataFrame, pair: str, date: pd.Timestamp) -> dict:
    g = prices[(prices["pair"] == pair) & (prices["date"] <= date)].sort_values("date").tail(WINDOW)
    return {
        f"{pair}_dates": (g["date"].to_numpy().astype("datetime64[D]").astype("int64")).tolist(),
        f"{pair}_close": g["close"].to_numpy().tolist(),
        f"{pair}_high": g["high"].to_numpy().tolist(),
        f"{pair}_low": g["low"].to_numpy().tolist(),
    }


def build_goldens(
    prices: pd.DataFrame,
    feats: pd.DataFrame,
    regimes: pd.DataFrame,
    detail: pd.DataFrame | None,
    n: int = N_GOLDENS,
) -> pd.DataFrame:
    """Raw windows for all pairs + Python's features and exact outputs for each sampled (date, pair)."""
    picks = _sample_goldens(regimes, n)
    reg_cols = [
        c for c in regimes.columns if c not in hm.POST_HMM_FEATURES or c in ("date", "pair")
    ]
    fr = feats.merge(regimes[reg_cols], on=["date", "pair"])
    bundles = hm.load_bundles()
    # exact filtered probs from the full history, once per pair (what Rust must reproduce)
    probs_by_pair: dict[str, pd.DataFrame] = {}
    for pair, g in feats.groupby("pair"):
        g = g.sort_values("date").reset_index(drop=True)
        b = bundles[pair]
        pr = hm.filtered_probs(b.model, b.scaler.transform(g[hm.HMM_FEATURES].to_numpy()))
        cols = [f"prob_{b.mapping[k]}" for k in range(hm.N_STATES)]
        probs_by_pair[pair] = pd.DataFrame(pr, columns=cols, index=g["date"])
    rows = []
    for row in picks.itertuples(index=False):
        rec = {"date": row.date, "pair": row.pair}
        for p in config.PAIRS:
            rec.update(_window(prices, p, row.date))
        f_row = fr[(fr["date"] == row.date) & (fr["pair"] == row.pair)].iloc[0]
        for c in [*features.BASE_FEATURES, *hm.POST_HMM_FEATURES]:
            rec[f"feat_{c}"] = float(f_row[c])
        for k, v in probs_by_pair[row.pair].loc[row.date].items():
            rec[k] = float(v)
        rec["regime"] = str(f_row["regime"])
        rec["regime_prob"] = float(f_row["regime_prob"])
        rec["hmm_entropy"] = float(f_row["hmm_entropy"])
        rec["days_in_regime"] = int(f_row["days_in_regime"])
        rec["change_risk_5d"] = float(f_row["change_risk_5d"])
        rec["anomaly_score"] = float(f_row["anomaly_score"])
        rec["anomaly_pct"] = float(f_row["anomaly_pct"])
        rows.append(rec)
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------------------
# manifest + build
# --------------------------------------------------------------------------------------
def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            cwd=config.ROOT,
        ).stdout.strip()
    except Exception:
        return "unknown"


def verify_manifest(bundle: Path) -> dict[str, bool]:
    """Recompute every file hash listed in the manifest; returns {file: ok}."""
    manifest = json.loads((bundle / "manifest.json").read_text())
    return {name: sha256(bundle / name) == h for name, h in manifest["files"].items()}


def build_bundle(version: str = BUNDLE_VERSION, models_dir: Path = config.MODELS_DIR) -> dict:
    out = bundle_dir(version, models_dir)
    out.mkdir(parents=True, exist_ok=True)
    prices = pd.read_parquet(config.PRICES_PATH)
    feats = pd.read_parquet(config.FEATURES_PATH)
    regimes = pd.read_parquet(config.REGIMES_PATH)
    detail_path = config.DATA_DIR / "siren_detail.parquet"
    detail = pd.read_parquet(detail_path) if detail_path.exists() else None

    model_versions = {}
    for pair, b in hm.load_bundles().items():
        (out / f"hmm_{pair}.json").write_text(json.dumps(hmm_to_json(b), indent=1))
        model_versions["hmm"] = b.version
    df = forecaster.assemble(feats, regimes)
    x_val = df[df["split"] == "val"]
    parity = export_forecaster(out, x_val)
    sb = siren.load_bundle()
    x_scaled = sb["scaler"].transform(siren.joined(feats, regimes)[siren.SIREN_FEATURES].to_numpy())
    parity.update(export_siren(out, x_scaled))
    model_versions["forecaster"] = json.loads((out / "forecaster.json").read_text())["version"]
    model_versions["siren"] = sb["version"]
    (out / "feature_spec.yaml").write_text(yaml.safe_dump(feature_spec(), sort_keys=False))
    goldens = build_goldens(prices, feats, regimes, detail)
    goldens.to_parquet(out / "goldens.parquet", index=False)

    files = sorted(p.name for p in out.iterdir() if p.name != "manifest.json")
    manifest = {
        "bundle_version": version,
        "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git_commit": git_commit(),
        "fxradar_version": fxradar.__version__,
        "model_versions": model_versions,
        "parity": parity,
        "tolerances": {
            "features": 1e-8,
            "model_outputs": PARITY_TOL,
            "anomaly_pct": "one rank step = 100 / len(train_scores_sorted) (rank statistic)",
        },
        "goldens": {
            "rows": int(len(goldens)),
            "window_rows": WINDOW,
            "includes": ["USDCHF 2015-01-15", "USDCHF 2015-01-16"],
        },
        "files": {name: sha256(out / name) for name in files},
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    hm.write_manifest(
        models_dir, bundle={"version": version, "path": str(out.relative_to(config.ROOT))}
    )
    return manifest


# --------------------------------------------------------------------------------------
# replay: the executable contract — from raw windows + bundle files only, reproduce the goldens
# --------------------------------------------------------------------------------------
def _gauss_loglik(
    x: np.ndarray, means: np.ndarray, precisions: np.ndarray, log_dets: np.ndarray
) -> np.ndarray:
    """log N(x | mu_k, Sigma_k) for all rows/states using precomputed precision + logdet -> (n, K)."""
    d = x.shape[1]
    out = np.empty((len(x), len(means)))
    for k in range(len(means)):
        diff = x - means[k]
        maha = np.einsum("ij,jk,ik->i", diff, precisions[k], diff)
        out[:, k] = -0.5 * (d * np.log(2 * np.pi) + log_dets[k] + maha)
    return out


def _forward_from_json(h: dict, x_scaled: np.ndarray) -> np.ndarray:
    from scipy.special import logsumexp

    log_b = _gauss_loglik(
        x_scaled, np.array(h["means"]), np.array(h["precisions"]), np.array(h["log_dets"])
    )
    log_a = np.log(np.clip(np.array(h["transmat"]), 1e-300, None))
    la = np.log(np.clip(np.array(h["startprob"]), 1e-300, None)) + log_b[0]
    la -= logsumexp(la)
    out = [la]
    for t in range(1, len(x_scaled)):
        la = logsumexp(la[:, None] + log_a, axis=0) + log_b[t]
        la -= logsumexp(la)
        out.append(la)
    return np.exp(np.array(out))


def replay_goldens(bundle: Path) -> pd.DataFrame:
    """Score every golden from its raw windows using ONLY bundle files; return per-output max abs diff.

    This mirrors what the Rust engine does at start-up. It uses fxradar.features for the feature
    formulas (the feature spec is a description of exactly that code) and the bundle's json/onnx for
    every model parameter — nothing is read from models/*.joblib.
    """
    goldens = pd.read_parquet(bundle / "goldens.parquet")
    hmm_json = {p: json.loads((bundle / f"hmm_{p}.json").read_text()) for p in config.PAIRS}
    fc = json.loads((bundle / "forecaster.json").read_text())
    si = json.loads((bundle / "siren.json").read_text())
    fc_sess = ort.InferenceSession(
        str(bundle / "forecaster.onnx"), providers=["CPUExecutionProvider"]
    )
    si_sess = ort.InferenceSession(str(bundle / "siren.onnx"), providers=["CPUExecutionProvider"])
    diffs: dict[str, float] = {}

    def upd(name: str, a: float, b: float) -> None:
        diffs[name] = max(diffs.get(name, 0.0), abs(float(a) - float(b)))

    for row in goldens.itertuples(index=False):
        rec = row._asdict()
        frames = []
        for p in config.PAIRS:
            frames.append(
                pd.DataFrame(
                    {
                        "date": pd.to_datetime(
                            np.array(rec[f"{p}_dates"], dtype="int64"), unit="D"
                        ),
                        "pair": p,
                        "open": rec[f"{p}_close"],
                        "high": rec[f"{p}_high"],
                        "low": rec[f"{p}_low"],
                        "close": rec[f"{p}_close"],
                    }
                )
            )
        feats = features.build_features(pd.concat(frames, ignore_index=True))
        g = feats[feats["pair"] == rec["pair"]].sort_values("date").reset_index(drop=True)
        h = hmm_json[rec["pair"]]
        x = (g[h["features"]].to_numpy() - np.array(h["scaler_mean"])) / np.array(h["scaler_scale"])
        probs = _forward_from_json(h, x)
        names = h["state_names"]
        state = probs.argmax(axis=1)
        regime = pd.Series([names[k] for k in state])
        run = hm.run_length(regime).astype(int)
        entropy = -(probs * np.log(np.clip(probs, 1e-300, None))).sum(axis=1)
        vol_trend = np.sign(g["vol_20"] - g["vol_20"].shift(10)).fillna(0.0)
        last = len(g) - 1
        for c in features.BASE_FEATURES:
            upd(f"feat_{c}", g[c].iloc[last], rec[f"feat_{c}"])
        upd("feat_hmm_entropy", entropy[last], rec["feat_hmm_entropy"])
        upd("feat_days_in_regime", run.iloc[last], rec["feat_days_in_regime"])
        upd("feat_vol_trend", vol_trend.iloc[last], rec["feat_vol_trend"])
        for k, nm in enumerate(names):
            upd(f"prob_{nm}", probs[last, k], rec[f"prob_{nm}"])
        upd("regime_prob", probs[last].max(), rec["regime_prob"])
        diffs["regime_mismatch"] = max(
            diffs.get("regime_mismatch", 0.0), float(regime.iloc[last] != rec["regime"])
        )
        # forecaster
        fx = {c: g[c].iloc[last] for c in features.BASE_FEATURES}
        fx.update(
            {
                "days_in_regime": run.iloc[last],
                "hmm_entropy": entropy[last],
                "vol_trend": vol_trend.iloc[last],
            }
        )
        for r_ in ["trend", "chop", "crisis"]:
            fx[f"regime_{r_}"] = float(regime.iloc[last] == r_)
        for p_ in ["GBPUSD", "USDCHF"]:
            fx[f"pair_{p_}"] = float(rec["pair"] == p_)
        xf = np.array([[fx[c] for c in fc["features"]]], dtype=np.float32)
        outs = fc_sess.run(None, {fc["onnx_input"]: xf})
        p_raw = float(outs[1][0][1]) if isinstance(outs[1], list) else float(outs[1][0, 1])
        p_cal = forecaster.calibrate(
            np.array([p_raw]), fc["calibration"]["a"], fc["calibration"]["b"]
        )[0]
        upd("change_risk_5d", p_cal, rec["change_risk_5d"])
        # siren
        sx = np.array(
            [[fx[c] if c != "ret_1d" else g["ret_1d"].iloc[last] for c in si["features"]]]
        )
        sx = (sx - np.array(si["scaler_mean"])) / np.array(si["scaler_scale"])
        recon = si_sess.run(None, {si["onnx_input"]: sx.astype(np.float64)})[0]
        score = float(((recon - sx) ** 2).mean())
        ref = np.array(si["train_scores_sorted"])
        pct = float(np.searchsorted(ref, score, side="right") / len(ref) * 100.0)
        upd("anomaly_score", score, rec["anomaly_score"])
        upd("anomaly_pct", pct, rec["anomaly_pct"])
    table = pd.DataFrame({"output": list(diffs), "max_abs_diff": list(diffs.values())})
    table["tolerance"] = np.where(table["output"].str.startswith("feat_"), 1e-8, 1e-6)
    table.loc[table["output"] == "regime_mismatch", "tolerance"] = 0.0
    # anomaly_pct is a rank statistic: a golden that is itself a calm-train day sits exactly on a
    # reference score, so 1e-13 of float noise can move it by ONE rank (100 / n_train). That is
    # exact for a percentile; the tolerance is one rank step (recorded in the manifest).
    table.loc[table["output"] == "anomaly_pct", "tolerance"] = (
        100.0 / len(si["train_scores_sorted"]) + 1e-9
    )
    table["ok"] = table["max_abs_diff"] <= table["tolerance"]
    return table


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    manifest = build_bundle()
    print(json.dumps(manifest, indent=2))
    table = replay_goldens(bundle_dir(manifest["bundle_version"]))
    print("\n== golden replay (Python, bundle files only) ==")
    print(table.to_string(index=False))
    if not table["ok"].all():
        raise SystemExit("golden replay FAILED")


if __name__ == "__main__":
    main()
