---
description: Phase 32 — the direction lab: labels, indicator zoo, purged CV, honest tests (next minor tag)
---

Read CLAUDE.md golden rules first. This phase opens the second room: a
direction-forecasting RESEARCH lab that does what trading firms actually do
— predict returns with some accuracy, then measure that accuracy honestly.
It changes the constitution before it changes the code.

## Step 0 — confirmed repo map (sanity-check, then confirm)
Pre-filled: features in data/features.parquet (+ features_ext from phase 23);
regime outputs in regimes_base/regimes.parquet; splits train ≤ 2016-12-31,
val 2017–2018, test 2019+ with the 5-day embargo; phase-14 backtest engine
with the lag law and vol-scaled costs; phase-15 strategies S1 (trend =
sign of mom_20), S2 (fade), S3 (regime gate) with the risk overlay; phase-16
stress lab; the phase-20 hash-chained ledger. Verify, report drift, WAIT.

## Task
FIRST, amend CLAUDE.md with the "two rooms" rule (new golden rule): direction
research is permitted ONLY inside `src/fxradar/lab/`; its outputs never
appear on any customer surface — no alerts, no API responses, no weekly
report, no widget, no proof-page headline; every lab surface carries the
phase-15 banner ("research demonstration — not a live trading system, not
advice"). THEN build the lab's foundations: labels, features, cross-
validation, and the honest evaluation of whether daily FX direction is
predictable here.

## Requirements
1. `src/fxradar/lab/labels.py`:
   - Vol-scaled forward returns: ret_fwd_k / (vol_20 · sqrt(k/252)) for
     k ∈ {1, 5, 20}.
   - Triple-barrier labels (López de Prado): per pair, profit-take and stop
     barriers at ±m·vol_20 (m from train only), vertical barrier at 10 days;
     label = which barrier was hit first. Hand-computed toy test.
   - Meta-labels: given a primary side from S1 (and separately S2), label 1
     if taking that side would have hit the profit barrier first NET of a
     cost haircut from the phase-14 cost model, else 0. This is the "even
     100% accuracy used wrongly loses money" problem, made into a target.
2. `src/fxradar/lab/indicators.py` → data/features_dir.parquet (research
   only — NEVER enters the contract, the bundle, or the wall): RSI(14),
   MACD(12,26,9) line/signal/histogram, Bollinger %B and bandwidth(20,2),
   stochastic %K/%D(14,3), normalized ATR(14), MA-crossover spreads as
   z-scores (5/20, 20/60, 50/200), ROC at 1/5/10/20/60 days, day-of-week
   one-hots. Hand-rolled in pandas/numpy — zero new dependencies. One-line
   rationale per indicator. Plus a clearly flagged RADAR BLOCK joined from
   existing artifacts: regime one-hots, regime_prob, hmm_entropy,
   days_in_regime, change_risk_5d, anomaly_pct, consensus agreement,
   days_to_event — kept separable for the phase-33 ablation.
3. `src/fxradar/lab/cv.py`: purged walk-forward and combinatorial purged
   K-fold WITHIN train ≤ 2016 (purge window = label horizon; embargo = 5
   days, the house standard). Model selection happens ONLY here; val
   2017–2018 for thresholds; the 2019+ frozen test is scored ONCE at the
   very end of phase 33, never here.
4. Models (restraint on purpose): scaled logistic regression, house-default
   XGBoost, and the raw primary signals as baselines. Targets: sign
   prediction per horizon AND the two meta-label tasks.
5. Honest evaluation → `reports/direction_lab.md`:
   - Directional accuracy WITH the Pesaran–Timmermann test p-value per
     model × horizon (accuracy without PT is banned in this repo).
   - AUC, calibrated Brier; a Model Confidence Set across the model ×
     horizon family (multiple-comparisons honesty).
   - The pre-registered expectation, written before results: at daily
     frequency on majors, raw sign edges are expected to be thin or absent;
     meta-labels may show real skill in FILTERING trades even where sign
     prediction is near coin-flip — that distinction is the finding.
6. Leakage armor (tests): shuffled labels collapse accuracy to base rate;
   a planted feature containing ret_{t+1} is caught by an explicit
   contamination detector; purging assertions verify no label window
   overlaps a training fold; features_dir passes truncation invariance.

## Do not
No new dependencies (no TA-Lib). Nothing from the lab touches customer
surfaces, the contract, the bundle, or Rust. No touching the 2019+ test.
No accuracy reported without its PT p-value. No tuning beyond one config
block, with the phase-15 no-further-tuning comment.

## Verify
- CLAUDE.md diff with the two-rooms rule shown to me first.
- Toy barrier test, leakage tests, truncation test green; `make test` green
  and CI still ~5 minutes.
- Read me reports/direction_lab.md with your honest interpretation,
  including the PT p-values table.
- CHANGELOG, commit `phase-32: direction lab foundations`, next minor tag.

## Teach me
Explain: triple-barrier and meta-labeling in plain words; what the
Pesaran–Timmermann test asks; why 52% accuracy can be gold at 1bp
institutional costs and dust at retail spreads; why purged CV exists. Quiz
me: (1) why does meta-labeling answer "even 100% accuracy used wrongly
loses"? (2) my accuracy is 53% with PT p = 0.21 — what do I tell an
interviewer? Critique my answers.
