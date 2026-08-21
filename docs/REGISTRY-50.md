# The 50-card registry — catalog, primitives, and build order

Replaces requirement 1 of phase 36. Same contract: the model names a card and passes
keys; the server resolves every value. Growing to 50 costs no latency and no tokens
because retrieval still injects only ~6 candidates per question.

---

## Part 1 — The eight primitives (build these first)

Fifty cards, eight renderers. Each primitive is written once in `widget.js`, styled
only from `widget-tokens.css`, with a text-equivalent and ARIA generator built in.
A card is then a registry entry: primitive + data bindings + caption templates.

| # | Primitive | Renders | Cards using it |
|---|---|---|---|
| P1 | `stat_block` | 1–4 big figures with labels and a sub-line | 14 |
| P2 | `bar_row` | horizontal labelled bars, one highlighted | 9 |
| P3 | `trace_band` | line + shaded uncertainty band (uPlot) | 6 |
| P4 | `ribbon` | coloured time strip with legend | 4 |
| P5 | `table` | labelled rows/columns, tabular numerals | 8 |
| P6 | `dot_row` | small state indicators with captions | 3 |
| P7 | `media_frame` | muted clip or image with caption + controls | 3 |
| P8 | `diagram_frame` | pre-authored SVG + caption | 3 |

Rules for every primitive: fixed height bands so boards never jump; skeleton state;
"as of" stamp slot; stale badge slot; export hook; caption + ARIA from the same
string so the spoken, written, and screen-reader versions never diverge.

---

## Part 2 — The catalog

Tier 1 = build now (answers most real questions). Tier 2 = build next.
Tier 3 = defined but **not built until the gap log asks for it**.

### Family A — State (6)
| # | Card | Answers | Primitive | Args | Tier |
|---|---|---|---|---|---|
| 1 | `condition_card` | "How does X look today?" | P1 | pair | 1 |
| 2 | `consensus_dots` | "Do the models agree?" | P6 | pair | 1 |
| 3 | `regime_probability_bars` | "How sure are you it's calm?" | P2 | pair | 2 |
| 4 | `siren_gauge` | "How unusual is today?" | P1 | pair | 2 |
| 5 | `pair_compare_table` | "Which pair is calmest?" | P5 | pairs | 1 |
| 6 | `drift_status` | "Is the model still healthy?" | P1 | — | 2 |

### Family B — Time and history (7)
| # | Card | Answers | Primitive | Args | Tier |
|---|---|---|---|---|---|
| 7 | `risk_trace` | "How has risk moved?" | P3 | pair, window | 1 |
| 8 | `regime_timeline_ribbon` | "How long in this regime?" | P4 | pair, window | 1 |
| 9 | `regime_history_table` | "When was the last crisis?" | P5 | pair | 2 |
| 10 | `period_compare_card` | "Versus last month?" | P1 | pair, anchor | 2 |
| 11 | `vol_trace` | "Is volatility rising?" | P3 | pair, window | 2 |
| 12 | `regime_duration_stats` | "How long do storms last?" | P2 | pair | 3 |
| 13 | `what_changed_card` | "What changed since yesterday?" | P1 | pair | 2 |

### Family C — Decision and money (10)
| # | Card | Answers | Primitive | Args | Tier |
|---|---|---|---|---|---|
| 14 | `treasury_light` | "Hedge, wait or ladder?" | P1 | pair | 1 |
| 15 | `var_es_bars` | "How bad is a bad week?" | P2 | pair, metric | 1 |
| 16 | `exposure_calculator` | "What about my €800k?" | P1 | exposure:from_user | 1 |
| 17 | `scenario_ladder` | "What if it moves 3%?" | P1 | pair, move:from_user | 1 |
| 18 | `impact_waterfall` | "Show me the damage" | P2 | pair, move:from_user | 2 |
| 19 | `move_frequency_bars` | "How often does that happen?" | P2 | pair, size_band | 1 |
| 20 | `hedge_compare_table` | "Forward vs ladder vs nothing?" | P5 | pair | 2 |
| 21 | `cost_of_waiting_curve` | "What does another month cost?" | P3 | pair | 2 |
| 22 | `breakeven_rate_card` | "At what rate do I break even?" | P1 | pair | 3 |
| 23 | `hedge_ladder_plan` | "How would I tranche it?" | P5 | pair, horizon | 3 |

### Family D — Trust and evidence (8)
| # | Card | Answers | Primitive | Args | Tier |
|---|---|---|---|---|---|
| 24 | `scoreboard_card` | "Why should I trust you?" | P1 | — | 1 |
| 25 | `coverage_plot` | "Are your bands honest?" | P3 | — | 2 |
| 26 | `ledger_row_receipt` | "Show me an actual sealed row" | P5 | date | 1 |
| 27 | `chain_verify_card` | "How do I verify it myself?" | P1 | — | 2 |
| 28 | `direction_evidence_card` | "Can anyone predict price?" | P1 | — | 1 |
| 29 | `calibration_curve` | "Are your probabilities real?" | P3 | — | 3 |
| 30 | `model_version_card` | "What's running right now?" | P5 | — | 3 |
| 31 | `champion_challenger_card` | "Which model is winning?" | P5 | slot | 3 |

### Family E — Context and drivers (7)
| # | Card | Answers | Primitive | Args | Tier |
|---|---|---|---|---|---|
| 32 | `event_countdown_strip` | "What's coming up?" | P6 | — | 1 |
| 33 | `feature_driver_bars` | "Why is risk elevated?" | P2 | pair | 1 |
| 34 | `cross_asset_card` | "What's the wider market doing?" | P5 | — | 2 |
| 35 | `event_study_card` | "What usually happens around SNB?" | P2 | event_type | 2 |
| 36 | `positioning_card` | "How is everyone positioned?" | P1 | — | 3 |
| 37 | `policy_tone_card` | "Have central banks turned?" | P3 | bank | 3 |
| 38 | `uncertainty_index_card` | "Is macro uncertainty high?" | P3 | — | 3 |

### Family F — Story and media (6)
| # | Card | Answers | Primitive | Args | Tier |
|---|---|---|---|---|---|
| 39 | `storm_replay_mini` | "How did COVID look?" | P4 | episode | 1 |
| 40 | `storm_replay_player` | "Show me, day by day" | P7 | episode | 2 |
| 41 | `storm_compare_card` | "Is today like March 2023?" | P5 | pair, episode | 2 |
| 42 | `weekly_briefing_clip` | "Give me the weekly briefing" | P7 | week | 2 |
| 43 | `milestone_card` | "How long have you been live?" | P1 | — | 3 |
| 44 | `snapshot_export_card` | "Send this to my CFO" | P7 | board_id | 2 |

### Family G — Explain and escalate (6)
| # | Card | Answers | Primitive | Args | Tier |
|---|---|---|---|---|---|
| 45 | `explainer_diagram` | "How does the siren work?" | P8 | diagram | 1 |
| 46 | `glossary_card` | "What does chop mean?" | P1 | term | 1 |
| 47 | `methodology_flow` | "Where does this number come from?" | P8 | metric | 2 |
| 48 | `faq_card` | "What do I get for CHF 79?" | P5 | topic | 2 |
| 49 | `ask_your_bank_card` | escalation: printable question list | P5 | topic | 1 |
| 50 | `metric_table` | **catch-all** — any whitelisted metrics | P5 | metric_keys | 1 |

**Totals:** 50 cards · Tier 1 = 20 · Tier 2 = 18 · Tier 3 = 12.

---

## Part 3 — What changes at 50 (the parts that actually need engineering)

1. **Near-neighbour disambiguation.** With 50 cards, several compete for the same
   question. Add a `disambiguation` block to each entry naming its rivals and the
   tie-break, and put those rules in the retrieved prompt slice. Known pairs:
   condition_card vs regime_probability_bars (word first, probabilities only when
   asked "how sure"); risk_trace vs vol_trace (risk unless the word is volatility);
   treasury_light vs scenario_ladder (light when they ask what to consider, ladder
   when they name a move); scoreboard_card vs coverage_plot (scoreboard unless the
   word is bands or coverage); storm_replay_mini vs storm_compare_card (compare only
   when today is referenced); metric_table only when nothing else fits.
2. **Retrieval quality gates.** Each entry needs 5–8 question_intents in EN/DE/FR.
   Add a retrieval test: for every golden question, the correct card must appear in
   the top-6 candidate slice ≥ 98% of the time — retrieval failure is invisible
   otherwise, because the model can only pick from what it was shown.
3. **Golden set grows to ~150** (≥3 questions per card) plus the adversarial and
   no-visual families. Report per-family coverage; a card with no golden questions
   cannot be marked built.
4. **Contract test per entry.** Every registry entry must resolve against a sample
   context pack in CI — a card pointing at a field that no longer exists fails the
   build instead of failing a customer.
5. **Board composition rules.** With more cards, boards get noisy. Cap at three,
   require distinct families for support cards, and forbid two cards from the same
   primitive in one board unless the roles differ (primary + explain).
6. **Cache pressure.** Cache key gains `locale`; pre-warm the top 10 boards only,
   not all 50 cards, or the nightly job balloons.

---

## Part 4 — Build order that protects you

- **Sprint 1 — primitives (2 days).** All eight, with skeleton/stale/export/ARIA
  built in. Nothing user-visible ships. This is the leverage.
- **Sprint 2 — tier 1, 20 cards (3 days).** These answer the large majority of real
  questions and include both catch-alls (`metric_table`, `explainer_diagram`) and
  the escalation card. Ship here; the assistant is now genuinely capable.
- **Sprint 3 — tier 2, 18 cards (2–3 days).** Depth: media, comparisons, coverage.
- **Tier 3, 12 cards — defined, not built.** They exist in the registry as specs
  with `status: planned`. Promote one only when `visual_gap_log.md` shows real users
  asking for it. Building all twelve on speculation is the one way this gets
  expensive without getting better.

Total to a capable product: ~5–6 days for 38 live cards, not 25 days for 50 guesses.

---

## Part 5 — Registry entry schema (the pattern, for all 50)

```yaml
- id: condition_card
  status: built            # built | planned
  tier: 1
  family: state
  primitive: stat_block
  question_intents:
    en: ["how does {pair} look today", "what's the regime", "is it calm right now",
         "current conditions", "give me today's read"]
    de: ["wie sieht {pair} heute aus", "wie ist das regime", "ist es gerade ruhig"]
    fr: ["comment se présente {pair} aujourd'hui", "quel est le régime"]
  args:
    pair: {type: enum, values: [EURUSD, USDCHF, GBPUSD]}
  bindings:
    word:  regimes.{pair}.regime
    risk:  regimes.{pair}.change_risk_5d
    band:  regimes.{pair}.conformal_interval
    siren: regimes.{pair}.anomaly_pct
    dots:  consensus.{pair}.votes
  disambiguation:
    rivals: [regime_probability_bars, siren_gauge]
    rule: "word first; probabilities only if the user asks how sure; gauge only if
           the user asks about unusualness"
  caption:
    en: "{pair} · {word} · risk {risk} ({band}) · siren {siren}"
  aria: en: "Condition for {pair} as of {asof}: {word}, change risk {risk}, band {band}"
  when_not: "user asked about history, money impact, or methodology"
```
