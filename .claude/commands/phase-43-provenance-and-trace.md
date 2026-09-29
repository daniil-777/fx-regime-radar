---
description: Phase 43 — provenance over process: one wait line, a clickable source strip, receipts that travel, and a full operator trace behind auth (next minor tag)
---

Read CLAUDE.md golden rules first. This phase builds two surfaces with deliberately
opposite philosophies. The customer surface shows almost nothing about how an answer
was produced and everything about where its numbers came from. The operator surface
shows all of it. Conflating them is the failure mode this phase exists to prevent:
engineers find the machinery fascinating, customers read a scrolling step log as
"this is slow and something failed."

## Step 0 — confirmed repo map (sanity-check, then confirm)
Pre-filled: phase-35 five gates; phase-36/38 registry, eight primitives, board and
SSE channel (`board`/`update`/`pending`/`clear`), receipt chips, export; phase-37
provenance gate and scenario engine; phase-39 golden set, snapshot, gap logs;
phase-40 answer packs with baked audio, cube, intent classifier, `path` label;
phase-41 prefix hash, cache metrics, per-path latency histograms; phase-42 router,
request slips, rooms, deadline, breakers, trace id per turn; design tokens →
`docs/widget-tokens.css`, `make lint-ui`; axum API keys, Prometheus, cost caps.
Verify, report drift, WAIT.

## Task
Formalise provenance as a first-class serialisable record; render it on the customer
surface as a quiet, clickable source strip; add exactly one wait line under strict
display rules; make provenance travel into exports; and build an operator trace view
with timeline, router, slips, gates, provenance map, prompt economics, deterministic
replay and one-click promotion of a turn into the golden set.

## Requirements

### A. The provenance record — build this first, everything renders it
1. A versioned serialisable object attached to every value that reaches speech, a
   card, or an export. Fields: `kind` ∈ {artifact_cell, cube_cell, ledger_row,
   document_chunk, scenario_output, user_utterance}; `locator` (artifact: file +
   column + date · cube: rollup definition + key · ledger: row id + chain hash +
   seal timestamp · document: doc + section + chunk hash · scenario: calculation id
   + inputs · utterance: the matched substring); `as_of`; `retrieved_at`;
   `source_tier`; `display_label` (human wording, never an internal identifier); and
   `versions` (context, intent, registry, prompt, gate-rules, model, voice) so any
   receipt can be interpreted years later under the rules that produced it.
2. The phase-37 provenance gate validates against this schema rather than an ad-hoc
   check. A value without a valid record cannot render or be spoken; the degradation
   ladder handles the gap.
3. Provenance is part of the answer payload, not a side channel — including inside
   phase-40 answer packs, so a precomputed answer carries the same receipts as a
   live one.

### B. The wait line — the only process visualisation permitted
4. Slow lane only, and only after a **400 ms threshold**: if the answer arrives
   faster the line never appears. Once shown it persists a **minimum 500 ms** so it
   cannot flash. These two rules are the difference between a calm interface and a
   twitchy one.
5. Text comes from a fixed, versioned, localised string table naming the destination
   in human words — "checking the sealed ledger", "counting past days", "reading the
   methodology". Never generated, never mechanics, never a tool name, count or
   timing.
6. At most one transition per turn. It reuses the existing pulse; no new animation.
   It disappears when the board lands. It **never reports a failure** — degradation
   is silent by design. `prefers-reduced-motion` drops the pulse, keeps the text.

### C. The source strip
7. Beneath every answer that used any source: compact mono chips carrying the
   `display_label`, the relevant date, and for ledger values the short chain hash
   with a check. At most four visible, then "n more". An answer built only from
   today's reading still shows a chip; absence of chips must mean "no data was used"
   — a refusal — never "we didn't bother".
8. Chips are interactive: activating one opens a detail sheet with the exact value,
   its human-worded source, the as-of date, and for ledger rows the sealed row, its
   hash and the verify link. Keyboard navigable, visible focus, ARIA labelled,
   bottom sheet at ≤ 480 px, touch targets ≥ 44 px.
9. **Vocabulary rule, enforced by lint:** no customer-facing string in any locale may
   contain internal identifiers or machinery words — tool or room names, column
   names, `slip`, `retrieval`, `embedding`, `token`, `ms`, `latency`, `query`,
   `cache`. Extend `make lint-ui` with this banned list across all three locale
   tables.

### D. Provenance that travels
10. Alongside the card PNG, generate a one-page **answer receipt** (PDF): the answer
    text, each value with its full provenance row, the as-of stamp, the AI-presenter
    disclosure, the standing disclaimer, and independent-verification instructions
    with the chain head.
11. Receipts are deterministic given the answer id and regenerable from the trace; no
    personal data in filenames, URLs, metadata or metric labels. A fiduciary
    receiving a client's receipt gets an auditable document, not a screenshot.

### E. The operator trace view — unconstrained by the customer aesthetic
12. `/ops/trace/{trace_id}` page and JSON endpoint, gated by an API key with an
    operator role, audit-logged on access, never linked from any customer surface and
    never rendered by the widget bundle.
13. Panels, joined by the phase-42 trace id: **Timeline** (every stage with start,
    end, duration — classifier, pack lookup, paraphrase, pre-router, retrieval, model
    rounds, each slip, gates, board flush, first audio — with the deadline drawn as a
    vertical line); **Router** (path taken, deciding stage, any precedence conflict,
    candidates with scores, which were shown); **Resolution** (the raw utterance, the
    conversation state applied, the resolved interpretation, and the echo line shown
    to the user); **Slips** (each slip as submitted, the query the server built, the
    `as_of` applied, cube-or-archive, row counts, tier, cache hit); **Gates** (each
    gate, pass/fail, reason, what regeneration changed); **Provenance map** (every
    value linked to its record); **Prompt economics** (prefix hash, cache hit/miss,
    input/cached/output tokens, cost).
14. **Deterministic replay:** re-run this exact turn against the frozen phase-39
    snapshot with the recorded seeds and inputs, and diff. A trace that cannot be
    replayed is a bug report without a repro.
15. **Promote to golden:** one control that converts the turn into a well-formed
    `eval/golden.yaml` item — question, locale, intent id, expected route, expected
    cards, gold values with `source_ref` taken from the provenance map — and opens it
    for review. This is the closed loop from production failure to regression test,
    and it matters more than any panel.
16. Traces retained for a configured window, redacted of user free text beyond what
    provenance requires, exportable as JSON.

### F. Strict separation, enforced by tests
17. Separate bundles: the customer widget must not import any trace component. A test
    asserts no operator string, timing, internal identifier or trace component appears
    in any customer render, in all three locales.
18. A test asserts `/ops/*` returns 401 without an operator key and appears in no
    sitemap, link or SSE payload sent to a customer session.

### G. Instrument your own decisions
19. Metrics: `wait_line_shown_total`, `wait_line_duration_ms`,
    `source_chip_click_total`, `source_detail_open_total`, `receipt_export_total`,
    `trace_view_open_total`, `trace_replay_total`, `golden_promoted_total`,
    `resolution_corrected_total` (the user rejecting an echoed interpretation — the
    single best signal that reference resolution needs work).
20. Review quarterly. If nobody opens a source chip in three months the detail sheet
    is decoration and should be simplified — measure your own UI the way you measure
    your models, and be willing to delete.

## Do not
No step logs, consoles, per-tool progress, spinners, percentages or timings on any
customer surface. No runtime-generated wait text. No wait line under the threshold.
No new animated elements. No internal identifiers in user-visible strings in any
locale. No trace surface without an operator key and an audit entry. No personal data
in traces, receipts, filenames, URLs or metric labels. No value rendered or spoken
without a valid provenance record. No exposing failures the ladder already absorbed.

## Verify
- Pack-path and fast-lane turns never render the wait line; a 300 ms slow-lane turn
  renders nothing; a 900 ms turn renders it at least 500 ms without flicker.
- Twenty sampled answers across all four paths: every value carries a valid record;
  chips open correct detail sheets; ledger chips show the sealed row, hash and a
  resolving verify link.
- Banned-token lint green across EN/DE/FR; separation tests green; `/ops/*` 401s.
- Trace view on a real slow-lane turn shows all six panels; replay reproduces;
  promote-to-golden produces a schema-valid item that passes `make eval-ci`.
- Answer receipt renders with the full provenance table and burnt-in disclosures;
  regeneration from the trace is byte-identical.
- Screenshots: desktop answer with source strip, detail sheet, mobile sheet at
  375 px, operator timeline with the deadline line, receipt PDF.
- `make lint-ui`, `make test` green; CI still ~5 minutes.
- CHANGELOG, commit `phase-43: provenance ui + operator trace`, next minor tag.

## Teach me
Explain: why provenance is worth more than process to a customer and process worth
more than provenance to an engineer; why a loading indicator needs both a delay
threshold and a minimum duration; why exposing an absorbed failure costs credibility
for no gain; why promote-to-golden matters more than any panel. Quiz me: (1) a
slow-lane turn finishes in 380 ms — what does the user see and why is that correct?
(2) three months in, chip clicks are near zero but receipt exports are high — what do
you conclude and what do you change? Critique my answers.
