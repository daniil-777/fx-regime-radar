---
description: Phase 12 — Rust inference engine with golden-vector self-test (v2.0.0)
---

Read CLAUDE.md golden rule 11. This is your first Rust phase — go slower,
ask the compiler to be your teacher, and have Claude explain every ownership
error until it makes sense.

## Task
Create `rust/fxradar-serve/` (cargo project) implementing the full scoring
path from raw prices to regime/risk/anomaly outputs, reading ONLY the model
bundle — plus a self-test binary that proves parity with Python.

## Requirements
1. Modules:
   - `bundle.rs`: load and verify the bundle (manifest SHA-256 checks first;
     any mismatch is a hard error). Serde structs for hmm json, feature spec,
     sidecars.
   - `features.rs`: compute the exact feature_spec features from a raw price
     window (log returns, rolling vols, vol_ratio, momentum, rng_hl, corr_20,
     ret_5d_abs) with ndarray. No lookahead, mirroring Python semantics.
   - `hmm.rs`: Gaussian log-likelihood per state using the precomputed
     precision matrices and log-dets from the bundle, plus the forward-filter
     recursion with log-sum-exp. Outputs filtered probs, regime, entropy.
   - `infer.rs`: run `forecaster.onnx` and `siren.onnx` via the `ort` crate;
     assemble the final ScoredRow (regime, regime_prob, change_risk_5d,
     anomaly_score, anomaly_pct).
2. `selftest` binary: load a bundle, replay every golden vector end-to-end
   (raw prices → features → models), print a per-output max-abs-diff table,
   exit nonzero if features diverge beyond 1e-8 or model outputs beyond 1e-6.
3. Error handling: a proper error enum with `thiserror`; no `unwrap`/`expect`
   in library code. The engine does no network and no file writes.
4. `criterion` benchmark: single-row full scoring latency and 10k-row
   throughput; record results in `rust/BENCH.md`.
5. Rust unit tests for features (hand-computed toy series, truncation
   invariance) and for log-sum-exp stability; `cargo clippy` clean.
6. CI: add a job that builds the crate and runs `cargo test` plus the
   selftest against the committed bundle.

## Do not
No Python calls, no PyO3 here — this side of the wall stands alone. No
reimplementing training. No skipping clippy warnings with allow attributes.

## Verify
- `cargo test` and `cargo clippy` clean; run the selftest and show me the
  full diff table; show the criterion numbers with one sentence of honest
  interpretation.
- CHANGELOG, commit `phase-12: rust inference engine`, tag `v2.0.0`.

## Teach me
Explain ownership and borrowing using one real error the compiler raised in
this phase; explain why the self-test lives in production code rather than
in Python's tests. Two interview questions (one must be "why did you
precompute the precision matrices in Python?"); critique my answers.
