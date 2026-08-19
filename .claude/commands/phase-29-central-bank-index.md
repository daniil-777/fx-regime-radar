---
description: Phase 29 — central-bank communication index, Stage 1: frozen lexicon + pinned FinBERT (next minor tag)
---

Read CLAUDE.md golden rules first. The narrow exception to "no LLM market
analysis": ~40 official letters a year from Fed, ECB, SNB, BoE — free,
timestamped, never revised — scored two ways with a hard wall between what
may touch history and what may not. A 4-part epic (~5–8 days), parts A→D,
verify each. Your CI stays sklearn-only and under 5 minutes: the neural leg
never enters CI.

## Step 0 — confirmed repo map (sanity-check, then confirm)
Pre-filled: ledger + deploy date from phase 20; challenger protocol +
features_ext from phase 23; anthropic SDK already a dependency (phase 09) —
NOT used in this phase; CI must stay light, so transformers/torch go in a
separate `requirements-nlp.txt` installed only on the VM/locally.
Verify, report drift, WAIT.

## Task
A hawkish/dovish/uncertainty index for FOMC + ECB + SNB + BoE statements.
Historical leg: a frozen public word-list (no memory → history-safe). Live
leg: a pinned FinBERT checkpoint (has memory → live-only, into the ledger).

## Requirements
A. Fetcher `src/fxradar/cb_text.py`: official English statements from the
   four banks' sites into data/cb/ with bank, type, publication datetime at
   the documented fixed times (ECB 14:15 CET, SNB 09:30 CET, BoE 12:00
   London, FOMC ~14:00 ET); dedup; idempotent; backfill as far as the sites
   allow. No other sources.
B. Historical leg: vendor the Loughran-McDonald word lists under
   data/lexicon/ with license note + pinned file hash; per-document hawkish,
   dovish, uncertainty scores as normalized counts; converted to daily
   point-in-time features in features_ext (non-null only from each
   publication timestamp). MUST pass truncation invariance bit-for-bit.
C. Live leg: one pinned FinBERT checkpoint, hash recorded in the repo;
   scored ONLY for documents published after the phase-20 deploy date, on
   the VM/locally via requirements-nlp.txt; scores written to the ledger.
   Code guard raises on any pre-deploy date; a test proves it. FinBERT
   output never enters training data or historical features. CI runs the
   lexicon leg only.
D. Evaluation: tone surprise = lexicon score minus the rolling average of
   that bank's last k statements; event study of surprise vs subsequent
   EURUSD/USDCHF volatility and regime shifts with the placebo band; a live
   tracking section on the proof page; lexicon features may join the
   CHALLENGER only (volatility/regime targets, never direction). README
   gains the one-paragraph parametric-look-ahead explanation.

## Do not
No general news, ever. No direction targets. No FinBERT/LLM scoring of
pre-deploy documents — not even "just to look". No unpinned models. No
torch/transformers in requirements.txt or CI.

## Verify
- Part B truncation invariance bit-for-bit, assertion shown; the live-only
  guard test; publication-time alignment spot-checked on three real days.
- Event-study figures with placebo; CI runtime still ~5 minutes.
- CHANGELOG, commits `phase-29a`…`phase-29d`, next minor tag.

## Teach me
Hawkish vs dovish in one sentence each; why a word list is history-safe but
FinBERT is not (where the memory lives); why tone SURPRISE rather than tone
level. Quiz: (1) FinBERT aces 2015 letters in a test — why is that
worthless? (2) why do fixed publication times matter so much? Critique.
