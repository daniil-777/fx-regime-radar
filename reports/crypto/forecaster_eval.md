# Forecaster evaluation — 5-day regime-change risk

_Generated 2026-08-18 13:09. Pooled across pairs. Train ≤ 2020-12-31 (5550 rows), val 2021–2022 (2160 rows), test 2023+ (3945 rows); 5-trading-day embargo on both sides of every boundary. The test set was scored ONCE for this report and its numbers are frozen._

## Setup

- Label: regime label differs at any of t+1..t+5 (train positive rate 23.4%).
- Features (15): vol_20, vol_60, vol_ratio, mom_20, rng_hl, corr_20, ret_5d_abs, days_in_regime, hmm_entropy, vol_trend, regime_trend, regime_chop, regime_crisis, pair_ETH-USD, pair_LTC-USD — all causal; HMM-derived ones from FILTERED outputs (asserted by a truncation-invariance test).
- Model: XGBClassifier, fixed hyper-parameters (no grid search — deliberate restraint), scale_pos_weight 3.28 from train, early stopping on val at iteration 208 (val PR-AUC 0.614).
- Probabilities: Platt-recalibrated on VAL (a=0.91, b=-0.93) because scale_pos_weight distorts raw XGBoost probabilities; raw numbers are shown in the scoreboard for honesty.
- Threshold 0.33 chosen on VAL to reach recall ≥ 60% on transitions (val recall 0.60, precision 0.52). Early-warning economics: a false alarm costs a look; a missed storm costs the reason the tool exists — so we buy recall and pay in precision, and we say so.

## Scoreboard — test set (2019+), scored once

Never accuracy: with a test positive rate of 23%, 'never changes' would score 77% accuracy and mean nothing.

| model | threshold | pr_auc | precision | recall | brier | n | pos_rate |
|---|---|---|---|---|---|---|---|
| XGBoost (ours, calibrated) | 0.330 | 0.548 | 0.418 | 0.661 | 0.149 | 3945 | 0.228 |
| base_rate | 0.230 | 0.228 | 0.228 | 1.000 | 0.176 | 3945 | 0.228 |
| logistic | 0.220 | 0.488 | 0.401 | 0.649 | 0.151 | 3945 | 0.228 |
| one_feature | 0.500 | 0.224 | 0.220 | 0.519 | 0.529 | 3945 | 0.228 |
| XGBoost (raw, uncalibrated) | 0.560 | 0.548 | 0.418 | 0.661 | 0.216 | 3945 | 0.228 |

Baselines: base rate = constant train positive rate; logistic = LogisticRegression on the same standardised features; one_feature = 'predict change if days_in_regime > train median' (a binary rule, so its PR-AUC is that of a step function).

## Calibration

Brier 0.1486 vs base-rate Brier 0.1761. The curve below compares predicted risk with observed change frequency in 10 quantile bins on the test set.

![calibration](forecaster_calibration.png)

## Drivers (SHAP)

![shap](forecaster_shap.png)

## Honest interpretation

XGBoost reaches PR-AUC 0.548 on the test set against 0.488 for the logistic baseline and 0.228 for the base rate — a lift of +0.059 over logistic. That is a clear margin over a linear model on the same features. At the chosen threshold it catches 66% of transitions with precision 42%. Calibration: Brier 0.1486 calibrated vs 0.2161 raw vs 0.1510 logistic — the recalibrated probabilities are at least as well calibrated as the linear model's. Regime transitions in a sticky HMM are intrinsically hard to time (the label flips on the HMM's own filtered decision), so no forecaster here should be read as a market call — it is a change-risk gauge.


_Educational tool. Not investment advice._
