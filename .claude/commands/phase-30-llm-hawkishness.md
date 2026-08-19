---
description: Phase 30 — Stage 2 (GATED): LLM-scored hawkishness, live-only, with the refusal note (next minor tag)
---

Read CLAUDE.md golden rules first. STOP AND CHECK THE GATE before any code.

## The gate (hard requirement)
Proceed only if BOTH hold: (1) the phase-29 live record covers ~two policy
cycles per bank (≈16 statements each for Fed/ECB, ≈8 for SNB's quarterly
schedule — count what exists); (2) lexicon tone-surprise shows a credible
event-study effect on volatility/regime, live, against a threshold agreed
with me beforehand. If either fails: write docs/stage2-decision.md with the
numbers and the decision NOT to build, commit it, stop. A documented no is
a deliverable.

## Step 0 — confirmed repo map (sanity-check, then confirm)
Pre-filled: reuse the phase-09 anthropic client pattern and key handling
(env/secrets, retries, fallback discipline); document store + ledger writes
from phase 29; proof page from phase 20. Verify, report drift, WAIT.

## Task
A third opinion on each NEW letter from a frontier model — with receipts —
and the one-page methodology note that is the real prize.

## Requirements
1. Live-only scoring: fixed prompt template versioned in the repo; for
   every call log the exact prompt, model name + version string, date, and
   raw response; scores to the phase-20 ledger; same pre-deploy guard as
   29C, tested. Runs on the VM/locally, never in CI.
2. Cost cap in config (~40 documents/year — the cap is hygiene); graceful
   skip + ops-log entry if the API is down (the phase-09 pattern).
3. Comparison panel on the proof page: lexicon vs FinBERT vs LLM on live
   documents only.
4. Centerpiece deliverable: docs/why-we-refuse-the-backtest.md — one page,
   plain language: the model has read the ending of every old story
   (parametric look-ahead), so post-cutoff live evaluation is the only
   honest test, and the hash-chained ledger implements it. Linked from the
   README top.
5. Customer surfaces never show LLM market narration; at most the
   hawkishness number moves behind the same template sentences.

## Do not
No historical scoring, ever. No market narration to users. No unpinned
prompts or unlogged calls. No proceeding past a failed gate "just to try".

## Verify
- Gate check shown WITH the numbers before any implementation.
- Guard test green; one real letter scored end to end, receipts in the
  ledger; I read the refusal note — a non-technical reader must get it in
  two minutes.
- CHANGELOG, commit `phase-30: llm hawkishness (gated)`, next minor tag.

## Teach me
Parametric look-ahead in one paragraph a recruiter would enjoy; why logging
prompt + model version makes the record auditable years later. Quiz: (1)
the vendor silently upgrades the model — what breaks and how do receipts
save us? (2) why is the refusal note worth more than an accuracy number?
Critique my answers.
