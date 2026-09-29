---
description: Phase 33 — forecasts to money: sizing, no-trade bands, the insurance blend, breakeven + deflated Sharpe (next minor tag)
---

Read CLAUDE.md golden rules, including the new two-rooms rule. Prediction
was the first step; this phase is the "use it smartly" step — the part that
decides whether accuracy survives commissions, spreads, and volatility.

## Step 0 — confirmed repo map (sanity-check, then confirm)
Pre-filled: phase-32 lab (labels, features_dir, purged CV, fitted direction
and meta-label models); phase-14 engine (lag law inside the engine,
vol-scaled cost model, foresight test); phase-15 framework (risk overlay:
change-risk scaling + siren stop + 10% vol targeting, inverse-vol blend,
per-regime attribution); phase-16 stress lab (cost shocks, breakeven
multiplier, lag shock, block bootstrap). Verify, report drift, WAIT.

## Task
Turn the lab's forecasts into positions the professional way, run them
through the EXISTING cost/stress machinery unchanged, and answer the
bridge question: does the radar make direction trading better?

## Requirements
1. `src/fxradar/lab/sizing.py`:
   - Side from the primary signal; size from the meta-model probability:
     zero below p* (chosen on val), then linear in (p − p*), capped —
     a capped fractional-Kelly-style map, documented plainly.
   - NO-TRADE BAND with hysteresis: only move the position when
     |target − current| exceeds a band calibrated on TRAIN to the
     phase-14 cost model (the band is the cost hurdle made explicit).
     Report turnover with the band on vs off — quantify the saving.
2. New strategies enter the phase-15 framework AS-IS (same overlay, same
   vol targeting, same caps): S4 = meta-labeled trend, S5 = meta-labeled
   fade. Rerun the blend with S1–S5; rerun the mutual-insurance verdict
   (correlation matrix, blend max-drawdown vs best single).
3. The bridge ablation, one table, whatever it says: each of S4/S5 trained
   (a) indicators only, (b) indicators + RADAR BLOCK; and S4/S5 run
   (c) with and (d) without the regime gate. Metric: NET Sharpe and
   breakeven cost. This is the "does the radar earn its keep in the
   direction room?" experiment — print the honest answer in the report
   and the README.
4. Economics through the phase-14 engine untouched (the lag law stays
   inside the engine): gross vs net, turnover, cost drag, breakeven cost
   multiplier per strategy — Daniil's number, presented first.
5. DEFLATED SHARPE RATIO (Bailey–López de Prado) for every strategy and
   the blend: count the trials honestly (all models × horizons × variants
   tried in phases 32–33 feed the trial count), report DSR next to Sharpe,
   and one paragraph explaining why the deflation is the honest part.
6. Frozen test 2019+ scored ONCE, at the end, results frozen into
   `reports/direction_money.md` with the pre-registered honesty paragraph.
   Stress reuse: cost 2x/3x/5x, one-day lag shock, block bootstrap on the
   blend including S4/S5.

## Do not
No re-tuning after seeing the test. No strategy without the overlay and
the siren stop. No leverage-cap changes. Nothing from this phase on any
customer surface. No Sharpe reported without its deflated twin. Expected
outcome stated in advance, phase-15 tradition: after realistic costs the
edge will be thin or absent; if the no-trade band and meta-labels rescue
net performance where raw signals bleed, that mechanism IS the finding.

## Verify
- Foresight test still executes and still kills a cheating signal.
- Turnover reduction from the band demonstrated with numbers.
- The bridge-ablation table and the breakeven table read to me line by
  line, with your honest interpretation; DSR shown next to every Sharpe.
- `make test` green. CHANGELOG, commit `phase-33: forecasts to money`,
  next minor tag.

## Teach me
Explain: why the no-trade band is transaction-cost theory in one sentence;
what deflating a Sharpe for the number of trials protects against; what
it would MEAN if the radar block helps sizing but not sign. Quiz me:
(1) breakeven cost 1.4x for S4 — is that deployable? (2) an interviewer
says "your blend Sharpe is 0.6, that is nothing" — my answer? Critique
my answers.
