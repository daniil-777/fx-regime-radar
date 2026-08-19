# Stage 2 decision record — LLM-scored hawkishness (phase 30)

*Decision date: 2026-08-19 · Decision: **DO NOT BUILD Stage 2 now** — the gate is closed.*
*Educational tool. Not investment advice.*

## The gate (phase-30 prompt, hard requirement)

Stage 2 (a frontier model scoring each NEW statement, live-only, with receipts) may proceed
only if BOTH hold:

1. the phase-29 **live** record covers about two policy cycles per bank — ≈16 statements each
   for FOMC / ECB / BoE (eight meetings a year) and ≈8 for the SNB (quarterly);
2. lexicon tone-surprise shows a **credible event-study effect on volatility / regime, on live
   statements**, against a threshold agreed beforehand (we use: the high−low |surprise|
   difference in 5-day vol_change or 10-day flip rate lies outside its 1000-shuffle
   permutation band, see `reports/cb_index.md`).

## The numbers on the decision date

Live = published on or after the phase-20 deploy date **2026-08-17** (`live_record.json`
"since"). Output of `python -m fxradar.cb_llm` (`cb_llm.gate_status(cb_llm.live_counts())`):

| bank | live statements | required | shortfall | statements on disk (2020→) |
|---|---|---|---|---|
| FOMC | 0 | 16 | 16 | 55 |
| ECB | 0 | 16 | 16 | 53 |
| SNB | 0 | 8 | 8 | 26 |
| BOE | 0 | 16 | 16 | 50 |

Condition 1: **fails** (0 of 56 required live statements).
Condition 2: **not assessable** — there are no live statements to run the event study on. The
historical lexicon event study (`reports/cb_index.md`) shows a clear calendar effect (five days
after any statement are more volatile than random days) but the *surprise* split stays inside
its permutation band for volatility on both pairs; it is the benchmark the live record will be
held to, not evidence for opening the gate.

## Decision

Stage 2 is **not built now**. A documented "no" is the deliverable. What ships instead:

* `src/fxradar/cb_llm.py` — complete but inert: `GATE_OPEN = False`, `gate_status()` re-checked
  on every run, no CLI bypass flag, same pre-deploy `LiveOnlyError` guard as FinBERT (tested),
  versioned prompt `prompts/cb_hawkishness_v1.txt`, receipts to `data/cb/llm_receipts.jsonl`
  (prompt sha256 + version, model, date, raw response), cost cap `MAX_DOCS_PER_YEAR = 60`,
  graceful skip + `data/ops_log.jsonl` line without a key. No real API call was made.
* `docs/why-we-refuse-the-backtest.md` — the one-page methodology note (the real prize).

## Re-check schedule

* Statements arrive at ~40 a year across the four banks (FOMC 8, ECB 8, BoE 8, SNB 4).
* **Interim re-check: 2027-02-17** (six months: expect ≈4/4/2/4 — still closed; review the
  live lexicon tracking on the proof page).
* **Earliest date both count thresholds can be met: ≈ 2028-09** (16 FOMC/ECB/BoE statements
  and 8 SNB assessments after 2026-08-17). The gate is re-run with
  `python -m fxradar.cb_llm` and this file is updated with the new numbers; flipping
  `GATE_OPEN` is a reviewed code change with a new decision record, never a flag.

*Educational tool. Not investment advice.*
