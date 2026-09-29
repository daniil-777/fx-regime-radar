---
description: Phase 38 — eight render primitives and the 50-card registry, with flat prompt cost and gap-log-gated growth (next minor tag)
---

Read CLAUDE.md golden rules first. This phase doubles the assistant's visual
vocabulary without doubling the code, the prompt, or the latency. It does so in one
specific order: extract eight render primitives from the existing cards with
byte-identical output, then express all fifty cards as registry entries over those
primitives, then make retrieval good enough that fifty candidates never reach the
model — only six do. Twelve of the fifty ship as specifications, not code, and are
promoted only when real users ask for them.

**Ordering note — read before Step 0.** If phase 36 is already built, this phase
begins as a pure refactor and must prove the existing cards render identically. If
phase 36 is NOT yet built, do the primitive layer here FIRST and build phase 36's
cards on top of it; do not hand-write bespoke cards and refactor them later.

## Step 0 — confirmed repo map (sanity-check, then confirm)
Pre-filled: phase-36 visual answers (config/visual_registry.yaml, retrieval into the
brain prompt, boards of 1–3 cards, server-side resolution, fourth gate, SSE channel,
docs/avatar-widget.html + widget.js, docs/widget-tokens.css generated from
design/tokens.json, export, EN/DE/FR, caching by context_version, golden set in
tests/golden_visuals.yaml, reports/visual_gap_log.md); phase-37 scenario engine
(src/fxradar/scenario.py, provenance gate, router, direction_evidence_card,
ask_your_bank_card); phase-35 brain endpoint and gates; artifacts
avatar_context.json, regimes/features/features_ext, treasury_risk.json, ledger +
scoreboard, status.json, storm reports, events.csv; `make lint-ui`; axum Prometheus;
CI sklearn-only ~5 min. The catalog to implement is `docs/REGISTRY-50.md`.
Verify, report drift, WAIT.

## Task
Build the primitive layer, migrate every existing card onto it with proof of
identical output, seed the full fifty-entry registry with tiers and statuses,
upgrade retrieval and disambiguation so selection quality does not degrade with
registry size, and prove that the model's prompt does not grow as the registry
grows. Ship tiers 1 and 2 as working cards; leave tier 3 as unselectable specs
whose promotion is driven by the gap log.

## Requirements

### A. The primitive layer (do this first)
1. Implement eight renderers in `widget.js`, styled only from
   `docs/widget-tokens.css`: `stat_block`, `bar_row`, `trace_band` (uPlot),
   `ribbon`, `table`, `dot_row`, `media_frame`, `diagram_frame`. Each must provide,
   built in: fixed height bands so boards never reflow; a skeleton state; an
   "as of" stamp slot; a stale badge slot; an export hook; and a single string
   source that generates the caption, the figcaption and the ARIA label together so
   spoken, written and screen-reader versions cannot diverge.
2. Migrate every card built in phases 36–37 onto a primitive. **Prove equivalence:**
   a visual-regression test renders each pre-existing card before and after and
   asserts pixel-identical output (or documents each intentional difference).
   No card may keep bespoke render code after this phase.

### B. Registry schema v3 and the fifty entries
3. Extend each `config/visual_registry.yaml` entry to carry: `id`, `status`
   (built | planned), `tier` (1–3), `family` (state | time | decision | trust |
   context | story | explain), `primitive`, `question_intents` (5–8 per locale in
   EN/DE/FR), `args` (enums and key references only — the schema must still contain
   no numeric type anywhere), `bindings` (dotted artifact paths), `disambiguation`
   (`rivals` plus a one-line `rule`), `caption` and `aria` templates per locale,
   `when_not`, and `owner_artifact` (which file must exist for it to resolve).
4. Seed all fifty entries from `docs/REGISTRY-50.md`: twenty tier-1 and eighteen
   tier-2 as `status: built`, twelve tier-3 as `status: planned`. Planned entries
   are documentation only — the resolver must refuse them and the retrieval index
   must exclude them. A test asserts a planned id can never appear in a board.
5. Write the disambiguation rules for every near-neighbour pair named in the
   catalog, and inject the rules for the retrieved candidates only — never the
   whole rule set.

### C. Retrieval, and the flat-prompt guarantee
6. Build the retrieval index over `question_intents` across all three locales at
   registry build time; cache it keyed by `registry_version`; rebuild on bump.
   At request time inject the top-6 candidates plus the two catch-alls
   (`metric_table`, `explainer_diagram`) and nothing else.
7. **Retrieval test (the invisible failure).** For every golden question, the
   expected card must appear in the top-6 candidate slice at least 98% of the time.
   Report recall@6 per family. A retrieval miss is not a model error and must be
   measured separately from selection accuracy.
8. **Flat-prompt assertion.** A test measures the injected registry slice in tokens
   with the registry truncated to 24 entries and with all 50, and asserts the
   difference is within noise. Registry growth must cost nothing at inference.

### D. Composition and safety at scale
9. Board rules: at most three cards; support cards must come from a different
   family than the primary; no two cards sharing a primitive in one board unless
   their roles differ (primary + explain). Null boards remain first-class.
10. All phase-36/37 gates apply unchanged, including provenance. Add a resolution
    pre-check: every `built` entry must resolve against a sample context pack in
    CI — a card whose `owner_artifact` or binding path no longer exists fails the
    build rather than a customer's question.

### E. Evaluation and growth
11. Grow `tests/golden_visuals.yaml` to ≥150 questions: at least three per built
    card, plus the existing no-visual, adversarial, stale-context and
    planted-number families. A card without golden questions may not be marked
    `built`. Targets: primary-selection accuracy ≥ 90%, coverage ≥ 80%,
    recall@6 ≥ 98%, and 100% correct routing on the investment-adjacent family.
12. Gap-log promotion workflow, documented in `docs/registry_growth.md`: a tier-3
    card is promoted to `built` only when `reports/visual_gap_log.md` shows the
    same unmet intent from at least N distinct sessions (N configurable, default 5)
    across at least two weeks. Promotion is a deliberate commit that adds golden
    questions first, then the entry status flip.

### F. Operations
13. Cache key becomes (registry_version, context_version, component, args, locale).
    Pre-warm only the top ten boards after the nightly build — never all fifty
    cards.
14. Prometheus: `visual_render_total{component}` (already), plus
    `retrieval_miss_total{expected_component}`, `visual_planned_blocked_total`,
    and `registry_slice_tokens` as a gauge.

## Do not
No bespoke card rendering outside the eight primitives. No rendering of any
`planned` entry. No growth of the injected prompt slice as the registry grows. No
numeric type anywhere in the tool schema, and no model-originated values. No
building tier-3 cards on speculation — the gap log promotes them. No new animated
elements beyond the existing budget. No hardcoded hex — `make lint-ui` stays green.
No heavy chart dependencies; uPlot remains the only plotting library and only for
`trace_band`. No card may ship without golden questions, a caption, an ARIA label,
and a `when_not` rule.

## Verify
- Visual-regression proof that every pre-existing card renders identically after
  the primitive migration; show the diff report.
- All fifty entries load; contract test resolves every `built` entry against the
  sample context pack; planned-id-unselectable test green.
- Retrieval: recall@6 ≥ 98% overall with the per-family table; show the worst three
  questions and what you did about them.
- Selection accuracy ≥ 90%, coverage ≥ 80% on the ≥150-question golden set;
  adversarial family still 100% routed with empty boards.
- Flat-prompt assertion passes at 24 vs 50 entries; show both token counts.
- Screenshots: each of the eight primitives in normal, skeleton and stale states,
  desktop and 375px; one board using three cards from three families.
- `make lint-ui` and `make test` green; CI still ~5 minutes.
- CHANGELOG, commit `phase-38: primitives + 50-card registry`, next minor tag.

## Teach me
Explain: why eight primitives beat fifty bespoke components, in maintenance terms a
manager would feel; why retrieval keeps the prompt flat and what would break if we
listed all fifty; why a retrieval miss is invisible in the output and therefore
needs its own metric; why twelve cards ship as specs rather than code. Quiz me:
(1) a user asks "is volatility picking up?" — name the rivals, the tie-break, and
the board that should render; (2) I add card fifty-one tomorrow — walk me through
every artifact I must touch, in order, and what fails first if I skip one.
