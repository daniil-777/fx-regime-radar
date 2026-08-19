---
description: Phase 21 — Bayesian online changepoint detection + regime consensus (next minor tag)
---

Read CLAUDE.md golden rules first. A second opinion that asks a different
question than the HMM: "how old is the current era — did it just end?"

## Step 0 — confirmed repo map (sanity-check, then confirm)
Pre-filled: returns = ret_1d per pair in `data/features.parquet`; HMM filtered
probabilities via `src/fxradar/hmm_model.py` outputs in regimes_base.parquet;
the third voter already exists — the phase-04 naive rule (stressed when vol_20
is above its trailing 80th percentile); ledger from phase 20; weather cards in
`app/app.py` via `app/ui.py`. Verify, report drift, WAIT.

## Task
Adams–MacKay BOCPD from scratch, a three-voter consensus with an agreement
meter, plain-language confidence lines, all logged to the ledger.

## Requirements
1. `src/fxradar/bocpd.py`, ~100 lines of numpy, zero new dependencies:
   Gaussian observation model with Normal-Inverse-Gamma conjugate prior
   (closed-form updates), constant hazard 1/60 (configurable), run-length
   pruning below 1e-6. Daily outputs per pair: MAP run length and
   P(changepoint within last 5 days).
2. Consensus in the same module: votes = HMM (crisis filtered probability
   over a train-era threshold), BOCPD (train-era-calibrated threshold on
   P(change ≤ 5d)), and the phase-04 vol rule reused verbatim. Output:
   agreement 0–3 + one template sentence per state ("3/3 agree: storm
   conditions", "1/3 — likely a one-day spike"). Templates only, no LLM.
3. Register scoring in run_daily; log votes + agreement + BOCPD outputs to
   the phase-20 ledger; consensus chips + meter on each weather card.
4. Tests: exact truncation invariance (prefix vs full history, bit-for-bit);
   synthetic planted mean/vol breaks flagged within a few days; determinism.

## Do not
No smoothing, no forward-looking calibration, no changepoint library
(writing it is the point), no direction language.

## Verify
- Truncation assertion shown; planted-break test green with one collapse plot.
- Ledger rows carry the votes; weather-card screenshot.
- CHANGELOG, commit `phase-21: bocpd consensus`, next minor tag.

## Teach me
Run-length posterior in one paragraph; what the hazard encodes; why online ⇒
causal and why we still test it. Quiz: (1) vol rule screams, BOCPD calm —
most likely situation? (2) why train-era-only thresholds? Critique my answers.
