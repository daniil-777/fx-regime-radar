---
description: Phase 22 — Mondrian conformal intervals on change risk + coverage receipt (next minor tag)
---

Read CLAUDE.md golden rules first. Every probability we publish now wears
honest error bars, with a public receipt proving the promised coverage.

## Step 0 — confirmed repo map (sanity-check, then confirm)
Pre-filled: forecaster (phase 07) splits train ≤2016 / val 2017–2018 / test
2019+ with 5-day embargo; change_risk_5d in regimes.parquet; regime labels in
regimes_base.parquet; ledger + proof page from phase 20; risk gauge on the
weather cards. Verify, report drift, WAIT.

## Task
Split conformal calibrated per regime (Mondrian), logged to the ledger, with
an empirical coverage tracker on the frozen test AND live.

## Requirements
1. Calibration set = the 2017–2018 validation years. Honest note, in code and
   report: these years also chose the early-stopping round and threshold, a
   documented dual use; the 2019+ test stays untouched, scored once.
2. Nonconformity = |realized outcome − predicted probability| on calibration;
   per regime r, q_r = 90th percentile (α = 0.1); interval = [p̂ ± q_r]
   clipped to [0,1]. Hand-rolled, ~30 lines, no new dependencies.
3. Register in run_daily: every daily forecast logs interval + regime-q to
   the phase-20 ledger; the weather-card risk gauge gains the band with a
   template line ("storm regime — bands are wide on purpose").
4. Coverage tracker: fraction of realized outcomes inside the interval on the
   frozen test and (as rows mature) live; rolling plot vs the 90% line;
   number surfaced on the proof page.
5. README paragraph: time series violate exchangeability, therefore we report
   empirical live coverage instead of citing the theorem — a feature, not a
   confession.
6. Tests: frozen-test coverage within 90% ± 3pp; crisis q > calm q;
   calibration dates strictly inside 2017–2018; deterministic.

## Do not
No touching the 2019+ test for calibration. No direction targets. No claims
of exact theoretical coverage anywhere user-facing.

## Verify
- Per-regime q table + calibration date assertions shown; coverage plot on
  the frozen test; first live rows carrying intervals.
- `make test` green incl. truncation invariance. CHANGELOG, commit
  `phase-22: mondrian conformal`, next minor tag.

## Teach me
Split conformal in four sentences; Mondrian per-regime honesty; the kinship
with VaR coverage backtesting (Kupiec/Christoffersen). Quiz: (1) why must
calibration never touch test? (2) "is the true risk definitely inside the
band?" — the honest answer? Critique my answers.
