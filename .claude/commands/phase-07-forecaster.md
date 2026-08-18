---
description: Phase 07 — XGBoost regime-change forecaster with SHAP (v1.1.0)
---

Read CLAUDE.md golden rules 1–3 twice. Build `src/fxradar/forecaster.py`.
This phase is the interview centerpiece — evaluation rigor over model cleverness.

## Task
Train a pooled XGBoost classifier answering: "will the regime change within the
next 5 trading days?" Produce calibrated risk, SHAP drivers, and a scoreboard
against baselines.

## Requirements
1. Labels: per pair, y = 1 if regime at any of t+1..t+5 differs from regime at
   t. Drop the final 5 rows per pair (incomplete future window).
2. Features (exactly these, one pooled dataset across pairs):
   vol_20, vol_60, vol_ratio, mom_20, rng_hl, corr_20, ret_5d_abs,
   days_in_regime, hmm_entropy, vol_trend, one-hot current regime (3 cols,
   drop one), one-hot pair (2 cols, drop one). All HMM-derived features come
   from the FILTERED outputs of phase-03 — assert this in a test by checking
   truncation invariance of the assembled feature matrix.
3. Splits by date with a 5-trading-day EMBARGO at each boundary (drop 5 rows
   per pair on each side): train ≤ 2016-12-31, val 2017–2018, test 2019+.
   Write a test that asserts the embargo gaps exist.
4. Model: XGBClassifier(n_estimators=1000, early_stopping_rounds=50,
   max_depth=3, learning_rate=0.04, subsample=0.8, colsample_bytree=0.8,
   min_child_weight=8, scale_pos_weight=neg/pos from TRAIN,
   eval_metric="aucpr", random_state=42), early stopping on val. No grid
   search — add a comment saying restraint is deliberate.
5. Threshold: choose on VAL to hit recall ≥ 0.6 on transitions; justify the
   early-warning economics (false alarms cheap, missed storms expensive) in
   the report.
6. Evaluation → `reports/forecaster_eval.md`, test set scored ONCE:
   PR-AUC, precision and recall at the chosen threshold, Brier score, and a
   calibration curve png. Scoreboard table against three baselines trained on
   the same splits: base rate (constant), LogisticRegression (scaled, same
   features), and the one-feature rule "predict change if days_in_regime >
   train median". Honest one-paragraph interpretation — if the win over
   logistic is thin, say so.
7. SHAP: TreeExplainer; global beeswarm png for the report; per-day top-3
   |SHAP| feature names into `top_drivers` (list of 3 strings).
8. Persist model as `models/forecaster_v1.1.0.json` (xgboost native). Register
   a scoring step in run_daily.py producing change_risk_5d and top_drivers
   into regimes.parquet (now the full contract minus siren columns).
9. Dashboard: add a "Change risk" element to each weather card — the
   probability as a horizontal gauge colored by band (<20 muted, 20–40 amber,
   >40 crisis red), with the top_drivers as small text beneath.

## Do not
Never report accuracy. Never touch the test set during tuning. No smoothed HMM
features. No features beyond the list.

## Verify
- Training run log with early-stopping round; the eval report read to me with
  your honest interpretation; calibration and beeswarm pngs shown.
- Leakage and embargo tests green; `make test` green; `make pipeline` now
  writes the new columns; app shows the gauge.
- CHANGELOG, commit `phase-07: forecaster`, tag `v1.1.0`.

## Teach me
Explain: why accuracy lies here, what calibration means to a trading desk, and
why the embargo exists, each in two sentences. Then three interview questions
(include "your PR-AUC is only modestly above logistic — is this worth it?");
critique my answers.
