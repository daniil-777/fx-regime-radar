---
description: Phase 11 — export the model bundle, research side of the wall (v1.4.0)
---

Read CLAUDE.md, including golden rule 11 (the wall). This phase runs AFTER
phase-09. Python's last act each cycle is to pack a bundle that production
can trust without trusting Python.

## Task
Build `src/fxradar/export.py` producing a versioned, self-describing model
bundle at `models/bundle_v{semver}/` — the only artifact that will ever cross
into the Rust serving layer.

## Requirements
1. Bundle contents:
   - `hmm_{pair}.json` per pair: state means, covariances, PLUS precomputed
     Cholesky-derived precision matrices and log-determinants (so Rust needs
     no linear-algebra decompositions), transition matrix, start probs,
     scaler mean/std, the frozen state→name mapping.
   - `forecaster.onnx`: convert the saved XGBoost model with onnxmltools;
     assert ONNX predictions match xgboost predictions on the validation set
     within 1e-6 and record the max diff in the manifest.
   - `siren.onnx`: convert the sklearn MLPRegressor with skl2onnx; same
     parity assertion; include the siren scaler params in a sidecar json.
   - `feature_spec.yaml`: ordered feature names, window lengths, and exact
     formulas (as documented strings) — the contract both languages compute.
   - `goldens.parquet`: 300 rows sampled across pairs, regimes and years,
     containing raw recent-price windows, the computed features, and
     Python's exact outputs (regime, filtered probs, change_risk_5d,
     anomaly_score). Include 2015-01-15 USDCHF deliberately.
   - `manifest.json`: bundle semver, model versions, file SHA-256 hashes,
     parity diffs recorded above, created_at, git commit.
2. CLI `python -m fxradar.export` builds the bundle and prints the manifest.
3. Tests: bundle round-trips (load json/onnx back in Python and reproduce
   golden outputs); manifest hashes verify; ONNX parity assertions.
4. Add export as the final step of the monthly refit path (not the daily
   pipeline), and document the bundle format in `docs/bundle_format.md`.

## Do not
No pickle files across the wall — json, onnx, yaml, parquet only (language-
neutral formats). No golden vectors generated from anything but the exact
models being shipped.

## Verify
- Build the bundle; show me the manifest and the recorded parity diffs.
- `make test` green. CHANGELOG, commit `phase-11: model bundle export`,
  tag `v1.4.0`.

## Teach me
Explain: why ONNX is the industry's research-to-production bridge, why
pickle must never cross a language wall, and what golden vectors contractually
guarantee. Two interview questions; critique my answers.
