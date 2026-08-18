---
description: Phase 04 — HMM validation and honesty report (v0.5.0)
---

Read CLAUDE.md. Build a validation module and produce a written report that
would survive a skeptical quant's review.

## Task
Create `src/fxradar/validate.py` plus a CLI that generates
`reports/hmm_validation.md` with embedded pngs, answering: are these regimes
real, stable, and useful — or statistical decoration?

## Requirements
1. Regime anatomy table per pair (train and test periods separately):
   frequency, mean duration in days, annualized vol, mean daily return,
   worst drawdown inside each regime.
2. Seed stability: the 5-seed agreement numbers from phase-03, as a table,
   with one honest paragraph interpreting them.
3. Baseline comparison: a naive classifier ("stressed" when vol_20 is above its
   trailing 80th percentile, else "quiet"). Show where the HMM agrees, and
   3 concrete dated examples where the HMM led the naive rule into or out of
   stress. If it did not lead, write that.
4. Economic-meaning check: a toy MA(50/200) trend strategy on each pair;
   report its Sharpe within each regime label (test period). The claim to
   check: trend-following should look best in "trend" and worst in "chop".
   Report whatever the data says.
5. Plots to reports/: per-pair timeline of close with regime-colored bands
   (design-system colors) and a vertical divider at 2017-01-01 labeled
   "out-of-sample →"; regime duration histogram.
6. The report ends with a Limitations section (daily data, label noise,
   regimes are descriptive not predictive) — written plainly.

## Do not
No cherry-picking. If a check fails, the report says so and we keep going —
honesty is the feature. Do not touch model code in this phase.

## Verify
- CLI produces the md and pngs; open and read the report to me section by
  section, flagging anything a reviewer would push on.
- `make test` still green. CHANGELOG, commit `phase-04: hmm validation`,
  tag `v0.5.0`.

## Teach me
Explain why we validate stability, baseline value-add, and economic meaning as
three separate questions. Then two interview questions ("how do you know your
regimes aren't overfitting?" must be one); critique my answers.
