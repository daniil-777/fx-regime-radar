---
description: Phase 25 — Treasury mode: the hedge/wait/ladder traffic light in francs (next minor tag)
---

Read CLAUDE.md golden rules first. The single most sellable object in the
system: one recurring treasurer decision, answered with risk math and a
price tag — never a direction call. No advisor module exists yet; this
phase builds it fresh.

## Step 0 — confirmed repo map (sanity-check, then confirm)
Pre-filled: regime-labeled daily returns join regimes_base.parquet ×
features.parquet (ret_1d); pairs EURUSD/USDCHF/GBPUSD; conformal intervals
(phase 22) and days_to_event (phase 23) in the ledger/features_ext; the app
computes nothing heavy (artifacts-only rule); axum handlers do no model
math. Verify, report drift, WAIT.

## Task
`src/fxradar/treasury.py`: regime-conditional VaR/ES, precomputed daily into
an artifact; a Streamlit "Treasury" page that turns exposure into a traffic
light with the cost of waiting in the user's currency; optional axum route
reading the same artifact.

## Requirements
1. Risk engine: historical-simulation 1-week VaR and ES at 95%/99% per
   regime per pair, estimated on regime-labeled train-era (≤2016) returns,
   documented; applied daily with the current filtered regime; pipeline
   writes `data/treasury_risk.json` (per pair × regime × level table +
   current regime pointer).
2. `app/pages/3_Treasury.py`: inputs = exposure amount, pair, horizon 1–12
   weeks, home currency (CHF default). Outputs from the artifact with
   arithmetic only: ES in home currency, the light (hedge / wait / ladder),
   a cost-of-waiting line ("waiting 1 more week on €800k risks ≈ CHF X at
   the 99% level"), and a rationale template combining consensus (21),
   interval width (22), days-to-next-event (23). Currency conversion via the
   latest close in prices.parquet; every number rounded.
3. Traffic-light rule table, deterministic and unit-tested, thresholds set
   on train era and documented: crisis OR (high risk AND wide interval) →
   hedge; calm AND narrow AND no event within 5 days → wait; else ladder.
4. Optional `GET /api/treasury` on the axum service reading
   treasury_risk.json — arithmetic only in the handler.
5. Compliance posture: the rule-7 disclaimer on the page and in any API
   text; a lint test bans direction words (rise, fall, buy, sell, target)
   from all templates; TODO note left for me: confirm Swiss FinSA specifics
   with a professional before charging.

## Do not
No direction language. No personalized-suitability claims. No leverage
suggestions. No unconditional (regime-free) numbers as the headline. No
model math in the app or handlers — artifact arithmetic only.

## Verify
- Sanity table: crisis ES ≥ calm ES for every pair, shown. Golden-path
  example end to end (page + route) with correct rounded conversion.
- Rule-table tests cover every branch; lint green; `make test` green.
- CHANGELOG, commit `phase-25: treasury mode`, next minor tag.

## Teach me
VaR vs ES in plain words; historical simulation and its limits; why regime
conditioning changes the numbers a lot. Quiz: (1) where exactly is the line
between risk information and investment advice here? (2) a user asks "so
will EURCHF go down?" — our answer? Critique my answers.
