---
description: Phase 36 — visual answers: a retrieved component registry, composable answer boards, interactive cards and explainer media, all numerically grounded (next minor tag)
---

Read CLAUDE.md golden rules first. This phase gives the phase-35 avatar a visual
voice: as it speaks, the answer materialises beside it as one to three brand-built
cards. The governing invariant survives untouched — the model chooses WHICH
components and WHICH keys, the server owns every displayed value — but the range of
answerable questions widens sharply through a larger retrieved registry, composable
boards, user-supplied exposure captured deterministically from the transcript, and
pre-authored explainer media for "how does this work" questions.

## Step 0 — confirmed repo map (sanity-check, then confirm)
Pre-filled: phase-35 avatar (Anam primary / HeyGen LiveAvatar Lite fallback;
`POST /avatar/brain` on axum with the versioned system prompt and three gates —
topic guard, direction-word lint, numeric grounding; mind = `data/avatar_context.json`
rebuilt daily by run_daily, plus `docs/avatar_knowledge.md`); artifacts
regimes.parquet, features.parquet + features_ext.parquet, treasury_risk.json,
ledger.parquet + live scoreboard, status.json (drift), storm replay reports
(COVID 2020, Credit Suisse 2023, SNB 2015), events.csv; design system
design/tokens.json → app/ui.py + `make lint-ui`; axum has API keys, rate limits,
Prometheus, cost caps; widget page is standalone static HTML/JS in docs/, iframed
into Streamlit; CI sklearn-only ~5 min; secrets env-only; Oracle VM CPU-only.
Verify, report drift, WAIT.

## Task
Build the answer-board system: a versioned registry of ~24 visual components
grouped into families; retrieval that injects only the most relevant entries into
the brain prompt so the registry can grow without degrading selection; a single
tool call returning speech plus an ordered board of 1–3 visuals; server-side
resolution of every value; a fourth gate covering the visual layer; an SSE
side-channel; and a token-built board UI with interactive affordances, explainer
media, export and localisation.

## Requirements

### The registry
1. `config/visual_registry.yaml`, versioned with `registry_version`. Each entry:
   id, family, question_intents (3–6 example phrasings), source artifact + field
   paths, allowed arg keys, when-to-use rule, when-NOT-to-use rule, caption
   template per locale, ARIA template, media type (svg | uplot | clip | static).
   Families and members:
   - **State** — condition_card, consensus_dots, drift_status, pair_compare_table
   - **Time** — risk_trace, regime_timeline_ribbon, regime_history_table
     ("when was the last crisis"), period_compare_card ("versus last month")
   - **Decision** — treasury_light, var_es_bars, exposure_calculator,
     hedge_ladder_plan, event_countdown_strip
   - **Trust** — scoreboard_card, coverage_plot, ledger_row_receipt (the actual
     sealed row + hash for a chosen date), model_version_card
   - **Story** — storm_replay_mini, storm_replay_player, weekly_briefing_clip
   - **Explain** — explainer_diagram (enum of pre-authored diagrams), glossary_card,
     methodology_flow
   - **Generic** — metric_table (renders any whitelisted metric keys as a labelled
     table; the coverage safety net), driver_bars
2. **Retrieval, not a giant prompt:** embed or keyword-index the question_intents at
   build time; at request time inject only the top-k (k≈6) candidate entries plus
   the always-available generic ones into the system prompt. The registry may grow
   past 24 without lengthening the prompt or degrading selection. Cache the index;
   rebuild on registry_version bump.

### The contract with the model
3. One tool, `answer_with_visuals`, returning `{ speech, board }` where `board` is
   an ordered array of 0–3 items, each `{ component, args, role }` with role ∈
   {primary, support, explain}. Zero visuals stays first-class and encouraged.
4. **Argument grammar — still no numbers.** Allowed arg value types: component-id
   enums, pair enums, `window` ∈ {20d, 60d, 120d, ytd, since_deploy},
   `anchor` ∈ {last_week, last_month, same_month_last_year, last_crisis},
   `episode` ∈ {covid_2020, credit_suisse_2023, snb_2015}, `metric_keys` (subset of
   a whitelist), `diagram` ∈ pre-authored ids, `locale` ∈ {en, de, fr}. The JSON
   Schema must contain **no number or integer type anywhere**; assert this in a test
   that walks the schema.
5. **User quantities come from the user, never the model.** A deterministic
   server-side parser extracts amount + currency + horizon from the USER's
   transcript (e.g. "800k euros over four weeks"), with range validation and an
   explicit `provenance: "user_utterance"` tag plus the matched substring. The model
   may only say `exposure: "from_user"`; if the parser found nothing, the card
   renders its input control empty and asks. Parsed values are echoed on the card
   ("from your question") and are editable by the user.

### Resolution, gates, and truth
6. Server-side resolver: (component, args) → concrete values read only from
   avatar_context.json (plus the pre-rendered media manifest). Missing or stale
   field ⇒ drop that board item, never fabricate, log the reason. All formatting
   server-side: currency, thousands separators, rounding, locale.
7. **Fourth gate**, after the existing three: component ∈ registry; args valid for
   that component; every displayed value resolved server-side; user-supplied
   quantities carry provenance and pass range checks; the resolved caption is
   re-run through the direction lint and the numeric-grounding check. Any failure ⇒
   that item is dropped (or the whole board, if it was the primary) and the answer
   degrades gracefully to speech.
8. Freshness contract: every card shows an "as of" stamp from context_version; if
   the pack is older than today's expected build, cards render with a muted stale
   badge and drift_status is auto-appended as a support item.

### Media
9. Explainer assets: pre-authored, versioned SVGs in `design/explainers/` (how the
   siren works; what a conformal band is; what the ledger proves; what filtered
   means; how the three voters combine). Zero data, zero hallucination surface,
   large coverage gain — these answer the "help me understand" class outright.
10. Motion media, pre-rendered by the pipeline, never generated live: short muted
    storm-replay clips (webm/mp4, ≤8 s, day-by-day scrub of a named episode) and
    the weekly briefing video from phase 27/35. Referenced through a media manifest
    with checksums; the resolver only serves ids present in the manifest.
11. Export and share: any card exports as a PNG at 2× with the disclosure line and
    the "as of" stamp burned in, plus an optional link to the public proof page.
    This is a distribution feature — a treasurer forwarding a card to a CFO is the
    cheapest marketing the product has. No user data in the filename or URL.

### Transport and UI
12. SSE side-channel `GET /avatar/visual/stream` (text/event-stream,
    `X-Accel-Buffering: no`), keyed by session. Event types: `board` (full replace),
    `update` (patch one card in place — e.g. the user drags the exposure slider),
    `pending` (skeleton while a clip loads), `clear` (barge-in / new turn). Flush
    the board BEFORE returning speech text to the vendor so cards land with the
    first words.
13. Board UI on the widget page, entirely from tokens.json → widget-tokens.css:
    a two-column card area at desktop width, primary card first; a header row with
    card count, pin and export; drill chips under cards that send a follow-up
    question (a chip is a suggested prompt, never a hidden action). Pinned cards
    persist across turns; unpinned cards are replaced. Cards are static — the only
    permitted motion remains the orb and the live dot, plus a ≤150 ms fade on card
    entry.
14. Interactive affordances, all client-side arithmetic over server-resolved values
    (never a re-inference): timeframe toggle on trace cards, exposure slider and
    horizon stepper on decision cards, locale switch, and a compare mode showing two
    pairs side by side. Any control that would need new data emits an `update`
    request through the same gates.
15. Mobile ≤ 480 px: avatar keeps the top third; the board becomes a bottom sheet
    with snap points (peek / half / full), one card per row, swipe between cards,
    export in the sheet header.
16. Localisation EN / DE / FR for captions, card labels and the disclosure line
    (Swiss market reality). Locale is a resolver input, never a model output beyond
    the enum. Numbers formatted per locale, tabular numerals preserved.
17. Accessibility: every card ships a text equivalent (figcaption) and an ARIA
    label carrying the same numbers the avatar speaks; keyboard navigation across
    cards and chips with visible focus; clips are muted, captioned and never
    autoplay with sound; `prefers-reduced-motion` disables the fade.

### Operations
18. Caching keyed by (registry_version, context_version, component, args, locale);
    invalidate on the daily rebuild. Pre-warm the ten most common boards after each
    pipeline run so the first question of the morning is instant.
19. Prometheus: `visual_render_total{component}`, `visual_board_size`,
    `visual_selection_fail_total{reason}`, `visual_cache_hit_total`,
    `visual_export_total`, histogram `visual_latency_ms` (decision → flush).
20. Evaluation, coverage-first: `tests/golden_visuals.yaml` with ≥60 questions
    spanning all six families, each with an expected primary component (or null),
    including ≥10 legitimate no-visual cases, ≥5 adversarial direction/advice
    questions (expect refusal, empty board), ≥3 stale-context cases, and a planted
    fabricated-number probe. Report BOTH primary-selection accuracy (target ≥ 90%)
    and **coverage** (share of questions a human judge would want a visual for that
    received an appropriate one; target ≥ 80%). Every production turn where the
    board was empty but the question looked visualisable is written to
    `reports/visual_gap_log.md` — that log is the roadmap for registry v3.

## Do not
No model-supplied numbers anywhere, including inside args. No code execution, no
model-generated chart specs, no live image generation. No visual that implies
direction: no forecast or projection lines, no price targets, no future-extending
paths, no buy/sell markers, no directional arrows on price. No stacking more than
three cards, and no visual when text suffices. No new animated elements beyond the
existing budget. No heavy chart libraries — hand-written SVG, with uPlot only for
the two plotted cards. No breaking `make lint-ui` or any existing page. No user
data in export filenames, URLs or logs. No clip generated at request time.

## Verify
- Golden set: primary-selection accuracy ≥ 90%, coverage ≥ 80%; print the confusion
  table and the per-family breakdown.
- All adversarial questions produce a branded refusal with an EMPTY board; show the
  transcript with gate decisions.
- Schema walk test proves no numeric type exists anywhere in the tool schema; the
  planted-number probe is blocked; a stale context pack produces the stale badge and
  auto-appended drift card.
- The user-quantity parser: ten phrasings across EN/DE/FR parse correctly, out-of-
  range values are rejected, and the matched substring is shown on the card.
- Latency: p95 `visual_latency_ms` < 300 ms; manual run confirms the board is on
  screen before the first spoken word.
- Screenshots: desktop board (two cards + explainer), mobile sheet at 375 px, an
  exported PNG with the disclosure burned in, and one storm clip playing muted.
- `make lint-ui` and `make test` green; CI still ~5 minutes (avatar/WebRTC excluded).
- CHANGELOG, commit `phase-36: visual answers`, next minor tag.

## Teach me
Explain: why the model supplies keys rather than numbers, and what class of bug that
design eliminates entirely; why retrieval over the registry matters once it passes
roughly a dozen components; why user quantities are parsed from the transcript
server-side rather than trusted from the model; the latency budget that lets the
board beat the first spoken word. Quiz me: (1) a user asks "how did this compare to
March 2023?" — walk through retrieval, the board the model should return, and every
value the server must resolve; (2) the exposure slider moves — why is that an
`update` rather than a new brain call, and what would go wrong if it weren't?
