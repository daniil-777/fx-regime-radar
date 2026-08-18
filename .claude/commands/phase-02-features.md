---
description: Phase 02 — feature engine with hard leakage tests (v0.3.0)
---

Read CLAUDE.md, especially golden rules 1 and 6. Build `src/fxradar/features.py`.

## Task
Compute the base feature set per pair from prices.parquet and write
`data/features.parquet` per the data contract.

## Requirements
1. `build_features(prices: DataFrame) -> DataFrame` computing, per pair:
   - ret_1d: log(close_t / close_{t-1})
   - vol_20, vol_60: rolling std of ret_1d × sqrt(252), windows 20 and 60
   - vol_ratio: (rolling std 5 of ret_1d × sqrt(252)) / vol_60
   - mom_20: close.pct_change(20)
   - rng_hl: 10-day rolling mean of (high − low) / close
   - corr_20: mean of the two 20-day rolling correlations of this pair's ret_1d
     with the other two pairs' ret_1d (align on date first)
   - ret_5d_abs: abs(close.pct_change(5))
   All rolling windows use only past and current rows. Drop the first 60 rows
   per pair (warm-up). Document each feature's one-sentence rationale in the
   docstring — copy the spirit of CLAUDE.md.
2. CLI `python -m fxradar.features` reads prices.parquet, writes
   features.parquet, prints shape and NaN report (post-warm-up NaNs must be 0
   except corr_20's own warm-up).
3. Tests in `tests/test_features.py`:
   - Toy correctness: constant price series → ret_1d 0 and vol_20 0; a small
     hand-computed series → exact expected vol_20 value.
   - TRUNCATION INVARIANCE (the leakage test): build features on the full
     fixture, then on the fixture minus its last 30 rows; assert the
     overlapping rows are exactly equal (pandas testing assert_frame_equal).
   - Schema matches the contract.

## Do not
No centering/scaling here (models own their scalers). No feature that peeks
forward. No extra features beyond the contract — restraint is the point.

## Verify
- `python -m fxradar.features` summary shown; `make test` green.
- Show me `features.parquet` head and describe() for one pair.
- CHANGELOG, commit `phase-02: feature engine`, tag `v0.3.0`.

## Teach me
Explain: what the truncation-invariance test proves and why it's the single most
important test in this repo; why vol_ratio is a "storm front" signal. Then two
interview questions on lookahead bias; critique my answers.
