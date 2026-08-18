---
description: Phase 17 — calibration arcade: forecasts, streaks, storm gallery (v2.5.0)
---

Read CLAUDE.md, especially golden rule 13. Prerequisites: phases through 07
(needs change_risk_5d) and 05 (dashboard). Cosmetic-plus-pedagogy layer —
build only after the core ships.

## Task
Build `src/fxradar/arcade.py` plus an "Arcade" dashboard page: a weekly
regime-change prediction game scored by Brier, with streaks, ranks, a storm
gallery, and learning badges.

## Requirements
1. The call: once per pair per week, the user sets P(regime changes within
   5 trading days) via slider and locks it with a nickname. ANTI-ANCHORING,
   enforced server-side: the model's change_risk_5d for that call is not
   rendered, sent, or logged to the client until after the lock is stored.
2. Resolution: a step in the daily pipeline checks matured calls (5 trading
   days elapsed), records the outcome from regimes.parquet, and computes
   Brier scores for the user and the model on identical questions. Season
   ledger: rolling mean Brier for both, win = lower Brier per resolved call.
3. Storage: sqlite at `data/arcade.db` (calls, resolutions, streaks, badges).
   Document plainly that free-tier hosting resets this file on redeploy and
   that the v3 Postgres migration makes it durable. No accounts, no email —
   nickname only, profanity-filtered.
4. Streaks and ranks: watch streak = consecutive days with a visit; ranks
   (observer → forecaster → storm chaser → regime master) driven ONLY by
   number of resolved calls and rolling Brier thresholds — never by
   boldness of predictions.
5. Storm gallery: `data/storms.yaml`, hand-curated and human-verified
   entries (SNB 2015, GBP flash crash 2016, COVID 2020, 2022) with date,
   pair, siren percentile, 3-line story. A card unlocks when its story page
   has been opened. The LLM may draft stories in this phase, but each entry
   is marked verified: true only after you personally check it.
6. Badges: methodology reader, first resolved call, well calibrated (Brier
   < 0.20 over 10+ calls), storm survivor (visited during a live crisis
   regime), beat the model (lower season Brier over 10+ calls). Each badge's
   unlock rule lives in one table in the code.
7. UI on the design system: the call card with lock flow, the observatory
   panel (rank, streak, season ledger), gallery, badges. Copy contains no
   urgency, no money, no trading language — the page banner reads "a
   calibration game: forecasting practice, not trading."
8. Tests: Brier math against hand values; resolution when the regime flips
   on day 3 vs day 6; the lock-before-reveal rule (model value absent from
   pre-lock render payload); streak rollover at midnight UTC; badge rules.

## Do not
No rewards tied to risk, frequency, or size. No confetti, countdowns, or
loss-streak shaming. No leaderboard of strangers in v1 (nickname ledger is
local). No dark patterns — a user who never plays sees zero nags.

## Verify
- Play one full cycle with me in dev: place a call, show the pre-lock
  payload contains no model value, fast-forward resolution with a fixture,
  show both Brier scores and the ledger update.
- `make test` green. CHANGELOG, commit `phase-17: calibration arcade`,
  tag `v2.5.0`.

## Teach me
Explain the Brier score with a rain-forecast example, why anti-anchoring
matters, and why we gamify calibration but never trading. Two interview
questions; critique my answers.
