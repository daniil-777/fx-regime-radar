---
description: Phase 03 — HMM regime model with filtered (causal) probabilities (v0.4.0)
---

Read CLAUDE.md golden rules 1 and 2. Build `src/fxradar/hmm_model.py`.
This is the technical heart of the project — take it slowly and explain as you go.

## Task
Fit one 4-state Gaussian HMM per pair, map anonymous states to named regimes,
produce CAUSAL filtered probabilities for the full history, and write the base
regime columns.

## Requirements
1. Inputs per pair: [ret_1d, vol_20, mom_20], standardized with a StandardScaler
   FIT ON TRAIN ONLY (train = dates ≤ 2016-12-31 per CLAUDE.md; also acceptable
   here: ≤ 2018 for the HMM — choose ≤ 2016 for consistency and say so).
2. Fit `GaussianHMM(n_components=4, covariance_type="full", n_iter=1000,
   random_state=42)` on the train window only.
3. FILTERED PROBABILITIES (this is the differentiator): implement
   `filtered_probs(model, X) -> ndarray[n, 4]` using the forward algorithm —
   per-frame log-likelihoods plus the transition matrix, normalized with
   logsumexp at each step so probs at time t use only observations up to t.
   Do NOT use `predict_proba` for outputs (it is smoothed and uses the future).
   Test it: on a 60-row toy series, assert filtered_probs at each t matches the
   last row of a brute-force recompute on the prefix X[:t+1] (atol 1e-8).
4. State → name mapping, computed from TRAIN-period state stats and frozen:
   sort states by mean vol_20 → lowest = calm, highest = crisis; of the middle
   two, larger |mean mom_20| = trend, other = chop. Persist the mapping.
5. Outputs per pair per day, appended to features and written to
   `data/regimes_base.parquet`: regime (argmax of filtered probs), regime_prob
   (max filtered prob), hmm_entropy (−Σ p log p of filtered probs),
   days_in_regime (run length of current label), vol_trend (sign of 10-day
   change in vol_20 — this is the third post-HMM contract feature).
6. Persist model + scaler + mapping per pair with joblib under
   `models/hmm_{pair}_v0.4.0.joblib`.
7. Stability check script (can live in the validation module): refit with seeds
   1..5, apply the mapping rule, report per-pair label agreement with the
   seed-42 model; warn below 80%.
8. Sanity assertions in tests: transition matrix diagonal mean > 0.8 (sticky),
   4 distinct states present in train, mapping is a permutation.

## Do not
Never call smoothed posteriors for any output or feature. No fitting on
post-2016 data. No per-day refits.

## Verify
- CLI run produces regimes_base.parquet; show regime counts and mean
  regime_prob per pair. `make test` green including the filtering test.
- Show me the transition matrix for EURUSD with one sentence per row.
- CHANGELOG, commit `phase-03: hmm with filtered probabilities`, tag `v0.4.0`.

## Teach me
Explain filtered vs smoothed with a weather analogy; why the transition matrix
is the reason HMM beats k-means here. Then two interview questions (one must be
"why filtered, not smoothed?"); critique my answers.
