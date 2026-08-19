---
description: Phase 23 — macro event calendar + cross-asset + free mood data + Yang-Zhang, challenger-only (next minor tag)
---

Read CLAUDE.md golden rules, especially rule 11 (the wall). This phase
answers "did you condition on the calendar?" WITHOUT breaking the Rust wall:
every new feature lives outside the frozen contract, consumed by a challenger
model only. feature_spec.yaml, the bundle, goldens, and Rust stay
byte-identical this phase.

## Step 0 — confirmed repo map (sanity-check, then confirm)
Pre-filled: prices have OHLC (data contract from phase 01) → Yang-Zhang is
feasible; features contract frozen in `data/features.parquet` + the bundle's
feature_spec.yaml; data layer `src/fxradar/data.py` (yfinance + frankfurter);
forecaster + splits from phase 07; monthly refit path bumps model_version;
chart bands drawn in `app/ui.py`. Verify, report drift, WAIT.

## Task
Scheduled-event countdowns, cross-asset context, two free point-in-time-safe
mood series, Yang-Zhang vol, a placebo-tested event study — all in a NEW
`data/features_ext.parquet` feeding a challenger forecaster that races the
frozen champion on the phase-20 ledger.

## Requirements
1. `data/events.csv` (date, type ∈ {FOMC, ECB, SNB, BoE, NFP, CPI}, source
   URL) hand-built from official published schedules; spot-check 10 rows.
   Features: days_to_next and days_since per type, causal.
2. Cross-asset in data.py with proper lags: DXY, VIX and 2y yields via FRED
   (find the free series; document any proxy), EURCHF close via yfinance as a
   CONTEXT series (not a scored pair). Lagged changes/z-scores standardized
   on train ≤ 2016 only.
3. Free mood: daily US EPU (FRED USEPUINDXD); weekly CFTC COT leveraged-money
   EUR net positioning with the release lag modeled EXPLICITLY (Friday
   release covers Tuesday data — the feature becomes known on release date;
   test that lag).
4. `yang_zhang(window=20)` in features code, written to features_ext as
   vol_20_yz (the frozen vol_20 in the contract is untouched). README
   ablation: regime timeline + HMM refit comparison using vol_20_yz on a
   RESEARCH copy only — the shipped HMM and bundle stay as-is; adopting YZ
   into the wall happens at the next scheduled bundle rebuild, listed as a
   follow-up.
5. Event study script: window −10..+10 per event type; average change risk
   and regime-flip frequency per relative day; placebo band from ≥1000
   random non-event draws; one figure per type into reports/; event markers
   on the dashboard timeline.
6. Challenger: retrain the forecaster WITH features_ext as
   models/forecaster_challenger_v*.json (same splits, embargo, no accuracy);
   register its scoring so BOTH champion and challenger write to the ledger
   with distinct model_versions; promotion criteria written down (challenger
   leads live PR-AUC after N matured days) — promotion itself is a later,
   deliberate act via the refit path.

## Do not
No realized announcement values or surprises (needs point-in-time consensus
data). No news scraping, no Google Trends. No change to features.parquet,
feature_spec.yaml, the bundle, goldens, or Rust. No silent champion swap.

## Verify
- Automated causality check: every features_ext column at date t computable
  from information dated ≤ t — including the COT lag test.
- Rust selftest still green against the unchanged bundle (prove the wall).
- Event-study figures with placebo; YZ ablation in README; both models
  writing ledger rows. CHANGELOG, commit `phase-23: calendar + context`,
  next minor tag.

## Teach me
Why scheduled dates are leakage-safe but released values are not; the COT lag
trap; Yang-Zhang in one paragraph; how the placebo separates signal from
luck. Quiz: (1) why is days_to_FOMC fair but the CPI print value dangerous?
(2) what exactly would promoting the challenger require? Critique my answers.
