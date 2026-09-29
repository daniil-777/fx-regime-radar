---
description: Phase 37 — the answer engine: scenario pricing, hedging mechanics, sealed direction evidence, and a hard advisory boundary (next minor tag)
---

Read CLAUDE.md golden rules first. This phase closes the biggest gap in the
assistant: the questions people actually ask are about money and direction, and
today they hit a dead end. From now on those questions get the strongest answer in
the product — the measured research evidence, then a scenario engine that prices
the move the USER is worried about. The rule that changes: refusal becomes routing.
The rules that do not change: the assistant never makes a forward-looking price or
direction statement, and never tells anyone what to do.

## Step 0 — confirmed repo map (sanity-check, then confirm)
Pre-filled: phase-25 treasury (treasury_risk.json, regime-conditional VaR/ES,
traffic light, cost-of-waiting); phases 32–34 direction lab (triple-barrier +
meta-labels, purged CV, Pesaran–Timmermann tests, breakeven cost multiplier,
deflated Sharpe, research rows sealed in the ledger under scope="research",
docs/DIRECTION_NOTES.md); phase-35 avatar (brain endpoint, context pack, knowledge
pack, three gates: topic guard, direction lint, numeric grounding); phase-36 visual
answers (registry + retrieval, boards of 1–3 cards, server-side resolution, fourth
gate, SSE, export, EN/DE/FR); artifacts prices/features/regimes/ledger; axum keys,
rate limits, cost caps, Prometheus; `make lint-ui`; CI sklearn-only ~5 min.
Verify, report drift, WAIT.

## Task
Build four things and wire them into the phase-36 board: a deterministic scenario
engine that prices user-supplied moves against user-supplied exposure; a hedging
mechanics knowledge base; a direction-evidence surface fed only by the sealed lab
record; and a hard advisory boundary with an escalation path to a human. Together
they convert the "will it go up / what should I do" class — the single largest
share of real questions — from a dead end into the most persuasive thing the
product does.

## Requirements

### 1. The scenario engine (the core unlock)
`src/fxradar/scenario.py`, pure deterministic arithmetic over artifacts:
- Inputs: exposure amount + currency + horizon, and a move size — all supplied by
  the USER, parsed server-side from the transcript with provenance tags (phase-36
  parser) or chosen from a ladder (−5, −3, −1, +1, +3, +5 %). The model may never
  originate any of these numbers.
- Outputs: impact in home currency if that move occurs; the same exposure hedged
  today at the current forward (forward points from the rate differential, sourced
  and dated, with the assumption stated); the difference; and the break-even rate.
- Context, strictly descriptive: how often a move of that size over that horizon
  occurred historically, split by regime, computed from labelled history and
  labelled in the UI as historical frequency, never as a probability of the future.
  Round, format, and localise server-side.
- Unit tests against hand-computed examples; a test asserting no scenario output is
  phrased as a prediction.

### 2. Scenario media
New registry components (phase-36 grammar; keys and enums only): `scenario_ladder`
(the move selector plus impact), `impact_waterfall` (exposure → move → hedged
comparison), `move_frequency_bars` (historical frequency by regime, current regime
marked), `hedge_compare_table` (unhedged / forward / ladder outcomes for the chosen
move). All hand-built SVG from tokens; uPlot only where a plotted axis is needed.

### 3. Hedging mechanics knowledge base
`docs/hedging_knowledge.md`, versioned and lint-clean: forwards and forward points,
laddering and tranching, collars and vanilla options at a conceptual level, natural
hedging, invoice-currency choice, rollovers, credit lines and margin, typical SME
bank practice, and the vocabulary a treasurer needs. Every entry is descriptive and
ends with the questions to put to their bank or fiduciary — never a recommendation.
This is what makes the assistant feel expert without giving advice.

### 4. The direction answer, from the sealed record
`direction_evidence_card` component plus knowledge entries resolved ONLY from
phase-32–34 lab artifacts: measured hit rate, PT p-value, breakeven cost multiplier,
deflated Sharpe, trial count, and the one-line verdict. Every number resolved
server-side from the research ledger; if the lab has not been run, the card renders
"not yet measured" rather than anything else. Include the honest nuance: where
meta-labelling showed skill at filtering, say so, and say why it still does not
become a product feature.

### 5. Routing replaces refusal
Rewrite the topic guard as a ROUTER. A direction, recommendation, or "what should I
do" question produces, in this order: one sentence stating we do not forecast
direction and why; the `direction_evidence_card`; and an invitation to the scenario
engine ("tell me the move you're worried about and your exposure, and I'll price
it"). Localised EN/DE/FR. The old flat refusal remains only for genuinely
out-of-scope topics (tax, legal, other asset classes, personal finance).

### 6. The advisory boundary, enforced in code
The distinction the whole phase rests on: **the user supplies the premise, the
assistant prices it.** The assistant never originates a premise about the future and
never states what the user should do.
- Extend the lint beyond direction words to advice constructions: "you should",
  "I recommend", "I'd suggest", "the best option is", "it's a good time to", plus
  DE/FR equivalents. Fails the gate; regenerate once, then fall back to template.
- Every scenario surface carries the conditional framing ("if that move happens")
  and the standing disclaimer, in the user's locale.
- Provenance gate (fifth gate): every quantity rendered anywhere carries either
  `artifact` or `user_utterance` provenance with the matched substring; anything
  else is blocked. Log provenance per turn.

### 7. Escalation to a human
Triggers: three requests for a recommendation in one session; an exposure above a
configurable threshold; leverage, margin, speculation, tax or legal wording; or any
sign the user is treating the tool as an adviser. Response: a warm handoff — state
plainly that this is a conversation for their bank or fiduciary, and generate a
printable question list built from `docs/hedging_knowledge.md` tailored to what they
described. This is a feature, not a failure: it is exactly what the Treuhänder
partner channel wants to receive.

### 8. Research mode (gated, never public)
Behind an API key plus a one-time explicit acknowledgment, an authenticated
"research lab" surface exposing the phase-32–34 scorecard, purged-CV methodology,
MCS results and the sealed research equity curve — for interviews, recruiters, and
design partners. Never on free or public surfaces; never a forward-looking call;
every access audit-logged. A test asserts research content cannot reach the public
board, the weekly report, alerts, or the widget.

### 9. Audit and export
Every turn logged with question, routing decision, gate outcomes, provenance tags,
board component ids, and locale — retained, reviewable, exportable. Add a CFO
one-pager export (PDF): current conditions, the user's scenario with its
assumptions, the historical-frequency context, "as of" stamp, AI-presenter
disclosure and the standing disclaimer burned in. No personal data in filenames,
URLs or metrics labels.

### 10. Evaluation
Extend the golden set with an investment-adjacent family of ≥25 questions covering
direction, recommendation-seeking, product comparison, leverage, tax and legal,
and emotional framing ("I'm scared, just tell me what to do"). Targets: 100%
correct routing; zero advice constructions and zero forward-looking price
statements across a 500-turn adversarial red-team run including jailbreak attempts,
role-play framing, and multilingual paraphrase; escalation triggers fire on every
designed case. Report per-family coverage alongside routing accuracy.

## Do not
No forward-looking price, direction, or "probability that the market will…"
statements — historical frequency only, always labelled. No recommendations,
imperatives, or suitability judgments. No leverage, position sizing, or speculative
framing. No tax or legal answers. No model-originated numbers anywhere, including
scenario inputs. No research-mode content on any public surface. No unlogged turns.
No implying the scenario engine says what will happen — it says what would follow
IF the user's stated move happened. No new animations beyond the existing budget.

## Verify
- 500-turn red-team run: zero forward-looking price statements, zero advice
  constructions, in all three locales; show the failures caught and how they were
  handled.
- Routing set: every direction/recommendation question produces the evidence card
  plus the scenario invitation, never a bare refusal; escalation cases hand off with
  a generated question list.
- Scenario arithmetic matches hand-computed examples, including the hedged
  comparison and break-even rate; forward-point assumption stated and dated.
- Provenance gate: a fabricated number cannot render; every displayed figure traces
  to an artifact or a matched user substring.
- Research-mode isolation tests green; audit log complete for a sample session.
- CFO one-pager renders with disclosures burned in; desktop and 375px screenshots.
- `make lint-ui`, `make test` green; CI still ~5 minutes.
- CHANGELOG, commit `phase-37: scenario answer engine`, next minor tag.

## Teach me
Explain: the difference between pricing a premise the user supplied and supplying
one — and why that line is both the legal boundary and the honest one; why
historical frequency conditioned on regime is not a forecast; why the evidence card
is more persuasive to a treasurer than a prediction would be; where FinSA's line
between information and advice sits and which of these features sits closest to it.
Quiz me: (1) a user says "everyone says the franc will strengthen, do you agree?" —
walk through the router, the gates, and the exact board that should render; (2) why
does the scenario engine refuse to attach a probability to the user's chosen move,
when it happily reports how often such moves occurred? Critique my answers.
