---
description: Phase 26 — flagship storm replays + auto post-mortems (next minor tag)
---

Read CLAUDE.md golden rules first. Three storms every Swiss buyer remembers,
replayed exactly as the radar would have seen them — including the honest
parts. No scenario-explorer module exists; the replay engine is built here
on the real scoring path.

## Step 0 — confirmed repo map (sanity-check, then confirm)
Pre-filled: scoring path = run_daily stages loading saved models (never
refitting); phase-16 stress.py already isolates the SNB week, COVID, 2022;
phase-08 validated the siren on 2015-01-15 USDCHF; pairs are
EURUSD/USDCHF/GBPUSD (EURCHF only as a context series from phase 23);
ledger from phase 20. Verify, report drift, WAIT.

## Task
A replay engine (truncated reruns of the real scoring path), three flagship
reports, a live post-mortem generator — clearly separated from the live
record.

## Requirements
1. `src/fxradar/replay.py`: for a date range, feed data truncated at each
   day t through the SAME loaded-model scoring path run_daily uses; output
   per-day regime, change risk (+ interval once 22 exists), anomaly_pct,
   consensus. Reuse phase-16 window definitions.
2. Report A — COVID, Feb–Apr 2020, EURUSD: buildup, alarm timing, aftermath.
3. Report B — Credit Suisse, Mar 2023, USDCHF: the Zurich resonance piece.
4. Report C — SNB floor removal, 2015-01-15, USDCHF: the siren's validated
   scream, told day by day — PLUS the honest sidebar: what a pegged EURCHF
   looked like (suppressed vol blinds vol-based radars; the phase-23
   cross-asset context is the response). Publish whatever the replay shows;
   no massaging.
5. Every replay page carries "causal reconstruction — not the live record"
   linking to the proof page, and states the selection rule (well-known
   named crises) so nobody can call it cherry-picking.
6. Auto post-mortem: a run_daily step that, on live entry into crisis
   regime, drafts a day-by-day report into reports/ flagged for my review.
7. Tests: for dates the live ledger covers, replay equals ledger rows
   bit-for-bit; truncation test on the replay engine itself.

## Do not
No hindsight edits; no extra flattering windows; no blending replays with
the live record; no refitting inside replay.

## Verify
- Replay-equals-ledger assertion green; truncation test green.
- Three reports rendered; I will personally read report C for honesty.
- CHANGELOG, commit `phase-26: storm replays`, next minor tag.

## Teach me
Hindsight bias vs causal reconstruction; why publishing the honest sidebar
is the strongest page. Quiz: (1) why must replay share run_daily's code
path? (2) how would a dishonest report C look, and which test catches it?
Critique my answers.
