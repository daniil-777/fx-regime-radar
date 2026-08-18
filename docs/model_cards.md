# Model cards

One card per model. All three are trained on data up to 2016-12-31 only and scored forward; the
test period (2019+) is scored once and frozen. Data: Yahoo Finance daily OHLC for EURUSD, USDCHF,
GBPUSD since 2005 (cleaned, ECB-cross-checked). Features are strictly causal (truncation-invariance
tests). **Educational tool. Not investment advice.**

---

## 1. Regime nowcaster — Gaussian HMM (`hmm_{pair}_v0.4.0.joblib`)

| | |
|---|---|
| **Purpose** | Nowcast the current market regime per pair: calm · trend · chop · crisis. |
| **Model** | `hmmlearn.GaussianHMM(n_components=4, covariance_type="full", n_iter=1000, random_state=42)`, one per pair. |
| **Inputs** | `ret_1d`, `vol_20`, `mom_20`, standardised with a scaler fit on the train window only. |
| **Training window** | 2005-03 → 2016-12-31 (≈3 050 rows per pair). |
| **Scoring** | Forward algorithm → FILTERED probabilities P(state_t \| obs ≤ t). Outputs: regime (argmax), regime_prob, hmm_entropy, days_in_regime, vol_trend. Smoothed posteriors are never used. |
| **Naming rule (frozen)** | Lowest mean vol_20 = calm, highest = crisis; of the middle two, larger \|mean mom_20\| = trend, other = chop. Computed from train-period state stats. |
| **Evaluation** | `reports/hmm_validation.md`: regime anatomy train vs OOS (vol ordering holds OOS); five-seed label agreement 40–100 % (EURUSD mean 71 %, GBPUSD 86 %, USDCHF 81 %); vs a naive vol-percentile rule the HMM does not lead systematically; toy trend rule is not best in "trend". |
| **Known failure modes** | Trend/chop split is seed-sensitive; labels flicker at boundaries; USDCHF's "crisis" state collapsed onto the 20 SNB-shock days (its 2008–11 stress carries the "chop" name); Gaussian emissions absorb fat tails into the high-vol state. |
| **Version** | 0.4.0 (manifest: `models/manifest.json`). |

## 2. Change-risk forecaster — XGBoost (`forecaster_v1.1.0.json`)

| | |
|---|---|
| **Purpose** | Probability that the (filtered) regime label differs at any point in the next 5 trading days. A change-risk gauge — not a price call. |
| **Model** | `XGBClassifier(n_estimators=1000, early_stopping_rounds=50, max_depth=3, learning_rate=0.04, subsample=0.8, colsample_bytree=0.8, min_child_weight=8, scale_pos_weight=neg/pos, eval_metric="aucpr", random_state=42)`; no grid search. Platt recalibration fit on validation. |
| **Inputs (15)** | vol_20, vol_60, vol_ratio, mom_20, rng_hl, corr_20, ret_5d_abs, days_in_regime, hmm_entropy, vol_trend, regime one-hots (3), pair one-hots (2). Pooled across pairs. |
| **Splits** | Train ≤ 2016-12-31 (9 136 rows), val 2017–2018 (1 527), test 2019+ (5 922); 5-trading-day embargo on both sides of every boundary. |
| **Threshold** | 0.22, chosen on validation for recall ≥ 60 %. |
| **Evaluation (test, frozen)** | PR-AUC 0.548 (logistic 0.431, base rate 0.162, one-feature 0.143); precision 0.45 / recall 0.59; Brier 0.102 (raw 0.128, logistic 0.116). Calibration curve + SHAP beeswarm in `reports/`. Never accuracy. |
| **Explanations** | SHAP TreeExplainer; per-day top-3 \|SHAP\| features → `top_drivers`. |
| **Known failure modes** | The label is the HMM's own decision, so label noise caps achievable skill; regime transitions cluster in time; probabilities are for a 5-day window and say nothing about direction or size of moves. |
| **Version** | 1.1.0. |

## 3. Anomaly siren — MLP autoencoder (`siren_v1.2.0.joblib`)

| | |
|---|---|
| **Purpose** | Detect days that look unlike any calm day the model has learnt. Detection only. |
| **Model** | `MLPRegressor(hidden_layer_sizes=(8, 3, 8), max_iter=3000, early_stopping=True, random_state=42)` trained to reconstruct its input. |
| **Inputs (9)** | vol_20, vol_60, vol_ratio, mom_20, rng_hl, corr_20, ret_5d_abs, hmm_entropy, ret_1d — standardised with a scaler fit on the training set below. No pair identity (pair-agnostic by design). |
| **Training set** | Train-period days labelled calm with regime_prob > 0.7, pooled: 2 788 days, 2005-04-07 → 2016-12-30. |
| **Scoring** | anomaly_score = mean squared reconstruction error; anomaly_pct = percentile against the calm-train distribution; per-feature errors + nearest historical neighbour (same pair, train period, ±10 days excluded) in `data/siren_detail.parquet`. |
| **Evaluation** | `reports/siren_validation.md`: SNB 2015-01-15 is USDCHF's loudest day (rank 1); Brexit 2016-06-24 rank 1 for GBPUSD; 2016-10-07 flash crash pct 100; 68–82 % of March-2020 days ≥ 98th percentile. |
| **Known failure modes** | Percentiles saturate at 100 for anything beyond the calm-train maximum (rank by score, not percentile, for extremes); many merely-volatile days also score high; a shock's return shows a day late (Yahoo close quirk) while its intraday range shows on the day. |
| **Version** | 1.2.0. |

## 4. Narrator (not a model of the market)

`claude-haiku-4-5`, temperature 0.3, max_tokens 350, fixed system prompt; input = a JSON of the
numbers above only; deterministic template fallback. It never sees prices, news or history and is
asked to add nothing that is not in the JSON.
