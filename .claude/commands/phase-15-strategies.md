---
description: Phase 15 — strategies, blend, and the insurance overlay (v2.3.0)
---

Read CLAUDE.md golden rules 2, 5 and 12. Prerequisite: phase 14. This phase
turns model signals into positions — and proves (or disproves) that
strategies can insure each other.

## Task
Build `src/fxradar/strategies.py` with three strategies, a risk overlay, a
blend, and an honest evaluation report.

## Requirements
1. Strategies (each returns a per-pair daily position in [-1, 1], using only
   information through day t):
   - S1 trend: sign(mom_20), scaled by momentum strength, capped.
   - S2 mean reversion: −clip(zscore_5d, −2, 2) / 2 — fade short-term moves.
   - S3 regime gate: run S1 in 'trend' regime, S2 in 'chop', half-size S1 in
     'calm', flat in 'crisis'. This is the app's thesis expressed as a
     strategy.
2. Risk overlay, applied to every strategy (the "insurance"): multiply
   positions by (1 − change_risk_5d) when risk > 0.3; force flat whenever
   anomaly_pct > 98 (the siren stop). Volatility targeting: scale final
   positions so each strategy runs at ~10% annualized vol using vol_20,
   leverage capped at 2x.
3. Blend: inverse-volatility weights across S1–S3, recomputed monthly from
   trailing realized strategy vol (no lookahead). Report the pairwise
   correlation matrix of strategy net returns and whether the blend's max
   drawdown beats the best single strategy — that is the mutual-insurance
   claim, tested rather than asserted.
4. Parameters: the few that exist (windows, caps, thresholds) are chosen on
   train (≤2016) + validation (2017–18) ONLY, listed in one config block
   with a comment forbidding further tuning. Test period 2019+ is scored
   once and frozen.
5. Evaluation → `reports/strategy_eval.md`: gross vs net metrics for S1, S2,
   S3 and the blend; per-regime Sharpe attribution table (does trend really
   earn in 'trend' and bleed in 'chop'? report whatever is true); equity
   curve pngs with regime-colored underlay and the out-of-sample divider;
   correlation matrix; one honest closing paragraph.
6. Dashboard: a "Strategy lab" page — net equity curves, drawdown chart,
   metrics table, per-regime attribution, and a visible banner: "research
   demonstration on daily data — not a live trading system."

## Do not
No parameter sweeps beyond the config block. No reporting the best strategy
only — all four always appear together. No leverage above the cap, ever.
Expected outcome, stated in advance: after realistic costs the edge will be
thin or absent; the deliverable is the framework and the honesty, and the
report says so in its own words.

## Verify
- Run the evaluation; read me the report including the per-regime table and
  the insurance verdict; show the equity curves.
- `make test` green (add tests: overlay forces flat on siren days; vol
  targeting hits 10% ± 2% on train). CHANGELOG, commit
  `phase-15: strategies and blend`, tag `v2.3.0`.

## Teach me
Explain: volatility targeting in plain words, why low correlation between
strategies is worth more than high Sharpe in one, and what the per-regime
attribution proves about the HMM. Two interview questions; critique my
answers.
