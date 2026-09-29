---
description: Phase 34 — the sealed direction record: research ledger, hard walls, interview pack (next minor tag)
---

Read CLAUDE.md golden rules, including the two-rooms rule. This phase gives
the direction lab the same spine the product has — forecasts sealed before
outcomes — and builds the wall that keeps the rooms separate, plus the
interview ammunition that makes the whole thing lethal.

## Step 0 — confirmed repo map (sanity-check, then confirm)
Pre-filled: phase-20 ledger (append-only, hash-chained, prev_hash/row_hash,
idempotent per date+pair, scored on maturity, notarized by the daily Action
commit); phase-32/33 lab outputs (side, meta probability, intended position
after the no-trade band, per pair and horizon); phase-14 cost model; the
proof page, weekly report, alerts, API, widget as customer surfaces.
Verify, report drift, WAIT.

## Task
Seal the lab's daily forecasts ex-ante in the same chain under a research
scope; score them on maturity AFTER COSTS into a live paper equity curve;
wall research off from every customer surface with tests, not promises;
ship the interview pack.

## Requirements
1. Ledger extension, backward compatible: add scope field — "product"
   (default, all existing rows) vs "research". A daily lab step seals, per
   pair and horizon: primary side, meta probability, intended position
   after the band, model_version. Same chain, same idempotency, same
   correction-by-new-row rule; verify_ledger.py unchanged and green.
2. Maturity scoring for research rows: realized barrier outcome AND
   after-cost paper P&L using the phase-14 cost model with the lag law —
   producing a live, sealed, net research equity curve and rolling hit
   rate with its Pesaran–Timmermann p-value, segmented by model_version.
3. THE WALL, enforced by tests: research rows are excluded from the proof
   page headline, the weekly report, alert payloads, the public API
   responses, and the widget — write a unit test per surface asserting no
   scope="research" content can appear there; add the direction-word lint
   to the lab templates' customer-facing exclusion list check.
4. New app page "Research lab" under the Analysis group, phase-15 banner on
   top: the sealed research scoreboard (net equity, hit rate + PT p, DSR),
   the bridge-ablation table, the breakeven table, and one honest verdict
   paragraph generated from the numbers.
5. README section "The direction question": three paragraphs — (1) yes,
   direction is partially predictable and here is our measured, sealed,
   after-cost answer; (2) why the PRODUCT still sells risk and never
   direction (economics of retail costs + the trust and regulatory moat);
   (3) the two-rooms architecture in one diagram-free paragraph. Link the
   Research lab page and the ledger verify instructions.
6. `docs/DIRECTION_NOTES.md` — the interview pack, ten Q&A in my voice:
   "can you predict price?" (the two-rooms answer with my measured
   numbers); what Pesaran–Timmermann tests; meta-labeling in 60 seconds;
   my breakeven-cost table and what it means; deflated Sharpe and my trial
   count; why 52% at institutional costs is a business and at retail
   spreads is a donation; how I control data snooping (purged CPCV + MCS);
   what the sealed research ledger proves that a backtest cannot; what I
   would need for intraday (point-in-time tick data, queue position,
   venue fees); and three questions to ask THEM: your breakeven cost per
   strategy? do you meta-label? how do you deflate Sharpe for trials?

## Do not
Never rewrite existing ledger rows (schema extension must not break the
chain — new rows carry scope; old rows validate as product by default).
No research content on any customer surface, enforced by the tests, not
by discipline. No claims in the README beyond the measured numbers.

## Verify
- Chain verifies from genesis after the extension; tamper test still
  fails loudly; one full research row sealed → matured → scored after
  costs, shown to me end to end.
- Every wall test green; grep the API/report/alert templates for research
  fields returns nothing.
- I read DIRECTION_NOTES.md and the README section as a skeptical prop-
  firm interviewer; fix what stumbles.
- CHANGELOG, commit `phase-34: sealed direction record`, next minor tag.

## Teach me
Then the final rehearsal: ask me the ten DIRECTION_NOTES questions cold,
one at a time, in random order, playing a Zurich prop-firm interviewer who
pushes back twice per answer. Grade me and list my three weakest answers
with fixes. This rehearsal is the phase's real deliverable.
