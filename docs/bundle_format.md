# Model bundle format — `models/bundle_v{semver}/`

The bundle is the **only** artifact that crosses the wall from Python (research) to Rust
(serving). It contains language-neutral files only — json, onnx, yaml, parquet — never pickle.
Rust replays every golden vector at start-up and refuses to serve on any mismatch.

| file | what | consumer notes |
|---|---|---|
| `manifest.json` | bundle semver, created_at, git commit, fxradar version, model versions, ONNX parity diffs, tolerances, golden summary, **SHA-256 of every other file** | verify hashes FIRST; any mismatch is a hard error |
| `hmm_{pair}.json` | `features` (order), `means` (K×d), `covariances`, **`precisions`** (Σ⁻¹) and **`log_dets`** (log\|Σ\|, both precomputed via Cholesky so the consumer needs no decompositions), `transmat`, `startprob`, `scaler_mean`/`scaler_scale`, `state_names` (index → regime), `train_end` | log N(x\|k) = −½(d·log 2π + log\|Σ_k\| + (x−μ_k)ᵀΣ_k⁻¹(x−μ_k)); forward filter from the window start with `startprob`, logsumexp-normalised each step |
| `forecaster.onnx` + `forecaster.json` | XGBoost as ONNX (float32 input `input`, outputs `label`, `probabilities`); sidecar: `features` (15, ordered), `calibration` {a, b} for Platt scaling, `threshold`, `horizon` | change_risk_5d = sigmoid(a·logit(p_onnx) + b) |
| `siren.onnx` + `siren.json` | MLP autoencoder as ONNX (float64 input `input` [n,9], output `output` [n,9]); sidecar: `features` (9), `scaler_mean`/`scaler_scale`, `train_scores_sorted` (2 788 floats) | x = (raw − mean)/scale; anomaly_score = mean((onnx(x) − x)²); anomaly_pct = searchsorted(train_scores_sorted, score, side=right)/n·100 |
| `feature_spec.yaml` | ordered feature names, windows and formulas as documented strings; HMM/forecaster/siren I/O contract; golden window length (600 rows) | the contract both languages compute |
| `goldens.parquet` | ≥300 rows sampled across pairs × years × regimes (+ USDCHF 2015-01-15/16): per row `date`, `pair`, for each of the 3 pairs `{pair}_dates` (int days since epoch), `{pair}_close/high/low` (last 600 trading days ≤ date), Python's features (`feat_*`, incl. hmm_entropy, days_in_regime, vol_trend), filtered `prob_{regime}`, `regime`, `regime_prob`, `hmm_entropy`, `days_in_regime`, `change_risk_5d`, `anomaly_score`, `anomaly_pct` | replay: raw windows → features (all pairs; corr_20 needs the others) → HMM forward → run length → forecaster → siren |

## Tolerances

- features: 1e-8 · model outputs (probs, change risk, anomaly score): 1e-6 · regime label: exact
- `anomaly_pct`: one rank step (100 / n_train ≈ 0.036) — it is a rank statistic and a golden that is
  itself a calm-train day sits exactly on a reference score.

## Why 600 rows

The forward filter forgets its start within ~250 rows (measured: identical to 1e-15), and the longest
regime run in history is 529 days, so a 600-row window reproduces every Python output exactly, including
`days_in_regime`. A shorter window bounds `days_in_regime` by its own length — send ≥ 600 rows.

## Building

`python -m fxradar.export` (also the last step of `make refit` / the refit workflow) writes the bundle,
prints the manifest and runs the Python replay (`export.replay_goldens`) — the same table Rust's
`selftest` produces.
