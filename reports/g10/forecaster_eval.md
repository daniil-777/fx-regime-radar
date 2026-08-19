# Forecaster evaluation — 5-day regime-change risk

_Generated 2026-08-19 17:34. Pooled across pairs. Train ≤ 2016-12-31 (30115 rows), val 2017–2018 (5090 rows), test 2019+ (19746 rows); 5-trading-day embargo on both sides of every boundary. The test set was scored ONCE for this report and its numbers are frozen._

## Setup

- Label: regime label differs at any of t+1..t+5 (train positive rate 18.3%).
- Features (22): vol_20, vol_60, vol_ratio, mom_20, rng_hl, corr_20, ret_5d_abs, days_in_regime, hmm_entropy, vol_trend, regime_trend, regime_chop, regime_crisis, pair_USDJPY, pair_GBPUSD, pair_USDCAD, pair_AUDUSD, pair_USDCHF, pair_NZDUSD, pair_EURGBP, pair_EURJPY, pair_USDSEK — all causal; HMM-derived ones from FILTERED outputs (asserted by a truncation-invariance test).
- Model: XGBClassifier, fixed hyper-parameters (no grid search — deliberate restraint), scale_pos_weight 4.45 from train, early stopping on val at iteration 139 (val PR-AUC 0.521).
- Probabilities: Platt-recalibrated on VAL (a=1.10, b=-1.46) because scale_pos_weight distorts raw XGBoost probabilities; raw numbers are shown in the scoreboard for honesty.
- Threshold 0.25 chosen on VAL to reach recall ≥ 60% on transitions (val recall 0.61, precision 0.44). Early-warning economics: a false alarm costs a look; a missed storm costs the reason the tool exists — so we buy recall and pay in precision, and we say so.

## Scoreboard — test set (2019+), scored once

Never accuracy: with a test positive rate of 18%, 'never changes' would score 82% accuracy and mean nothing.

| model | threshold | pr_auc | precision | recall | brier | n | pos_rate |
|---|---|---|---|---|---|---|---|
| XGBoost (ours, calibrated) | 0.250 | 0.551 | 0.478 | 0.577 | 0.110 | 19746 | 0.177 |
| base_rate | 0.180 | 0.177 | 0.177 | 1.000 | 0.146 | 19746 | 0.177 |
| logistic | 0.180 | 0.455 | 0.424 | 0.597 | 0.123 | 19746 | 0.177 |
| one_feature | 0.500 | 0.159 | 0.128 | 0.376 | 0.563 | 19746 | 0.177 |
| XGBoost (raw, uncalibrated) | 0.580 | 0.551 | 0.476 | 0.578 | 0.159 | 19746 | 0.177 |

Baselines: base rate = constant train positive rate; logistic = LogisticRegression on the same standardised features; one_feature = 'predict change if days_in_regime > train median' (a binary rule, so its PR-AUC is that of a step function).

## Calibration

Brier 0.1102 vs base-rate Brier 0.1457. The curve below compares predicted risk with observed change frequency in 10 quantile bins on the test set.

![calibration](forecaster_calibration.png)

## Drivers (SHAP)

![shap](forecaster_shap.png)

## Honest interpretation

XGBoost reaches PR-AUC 0.551 on the test set against 0.455 for the logistic baseline and 0.177 for the base rate — a lift of +0.096 over logistic. That is a clear margin over a linear model on the same features. At the chosen threshold it catches 58% of transitions with precision 48%. Calibration: Brier 0.1102 calibrated vs 0.1595 raw vs 0.1231 logistic — the recalibrated probabilities are at least as well calibrated as the linear model's. Regime transitions in a sticky HMM are intrinsically hard to time (the label flips on the HMM's own filtered decision), so no forecaster here should be read as a market call — it is a change-risk gauge.


_Educational tool. Not investment advice._
