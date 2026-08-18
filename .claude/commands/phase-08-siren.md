---
description: Phase 08 — MLP autoencoder anomaly siren (v1.2.0)
---

Read CLAUDE.md. Build `src/fxradar/siren.py`.

## Task
Train a small autoencoder on normal market days so that reconstruction error
becomes a daily "weirdness" score, then prove it screams at famous shocks.

## Requirements
1. Inputs: the 9 continuous features (vol_20, vol_60, vol_ratio, mom_20,
   rng_hl, corr_20, ret_5d_abs, hmm_entropy, ret_1d), standardized with a
   scaler fit on TRAIN calm-regime days only. Train
   `MLPRegressor(hidden_layer_sizes=(8, 3, 8), max_iter=3000,
   early_stopping=True, random_state=42)` to reconstruct its input, on
   TRAIN-period days labeled calm with regime_prob > 0.7, pooled across pairs
   with pair one-hots excluded (the siren is pair-agnostic; note why).
2. Scoring for every day: anomaly_score = mean squared reconstruction error;
   anomaly_pct = percentile of that score against the TRAIN calm distribution.
   Also keep the per-feature squared errors (for the phase-09 explainer) and
   the nearest historical neighbor: the train-period date with the closest
   feature vector (euclidean), excluding the surrounding ±10 days.
3. Known-events audit → `reports/siren_validation.md`: list the top-15
   anomaly_pct days per pair and check, honestly, whether they include
   2015-01-15 (SNB floor removal — USDCHF must light up or the phase fails
   review), 2016-06-24 and 2016-10-07 for GBPUSD, and March 2020 broadly.
   Include a full-history sparkline png of anomaly_pct per pair with those
   dates annotated.
4. Persist model + scaler `models/siren_v1.2.0.joblib`; register scoring in
   run_daily.py; regimes.parquet now matches the full contract.
5. Dashboard: "Anomaly siren" section — current anomaly_pct as a small dial or
   labeled number per pair (muted <90, amber 90–98, crisis red >98), a 2-year
   sparkline, and a "loudest days in history" table with dates and scores.
6. Tests: bottleneck architecture is (8, 3, 8); scaler fit only on calm train
   days (assert date range and labels of the fit set); scoring is
   truncation-invariant.

## Do not
No deep-learning frameworks — sklearn only, matched to data size. No training
on stressed days. No claim that the siren predicts anything; it detects.

## Verify
- Validation report read to me, including the SNB check result; sparkline pngs
  shown. `make test` and `make pipeline` green; app section demonstrated.
- CHANGELOG, commit `phase-08: anomaly siren`, tag `v1.2.0`.

## Teach me
Explain: why a bottleneck forces the network to learn "normal", and why we
train only on calm days, in plain language. Two interview questions (include
"why an autoencoder instead of a simple z-score?"); critique my answers.
