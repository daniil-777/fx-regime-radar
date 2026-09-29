---
description: Phase 40 — precomputed answer packs with baked audio, rollup cube, a leakage-free intent classifier, and conversation state (next minor tag)
---

Read CLAUDE.md golden rules first. The market moves once a day, so the answers should
be built once a day. This phase moves the common path off the request entirely, and
adds the two things a conversational product cannot work without: a classifier that
maps an utterance to an intent locally in under a millisecond, and server-side
conversation state so "and USDCHF?" means what a human means by it.

## Step 0 — confirmed repo map (sanity-check, then confirm)
Pre-filled: `pipelines/run_daily.py` register-a-step pattern; phase-35 brain, system
prompt, context pack, knowledge packs, five gates; phase-36/38 registry, eight
primitives, board schema, provenance; phase-37 scenario engine and router templates;
ElevenLabs Flash for TTS with audio passthrough to the avatar vendor; phase-39
`eval/golden.yaml` with `intent_id`, `precomputable`, `turn_context`, computed gold
values, frozen snapshot, `reports/eval_baseline.md`, pinned-version rule; axum with
Prometheus and cost caps; daily Action commits `data/`; CI sklearn-only ~5 minutes;
Oracle VM CPU-only. Verify, report drift, WAIT.

## Task
Add four things: precomputed answer packs including synthesized audio; a rollup cube
of common aggregations; an intent classifier trained on a corpus strictly separate
from the eval set; and conversation state with reference resolution. Serving order
becomes: resolve references → classify → exact pack → paraphrase pack → live.

## Requirements

### A. The canonical intent set
1. `config/intents.yaml`, versioned: each entry has `intent_id`, description, the
   parameters it varies over (pair and locale only — an intent needing a user-supplied
   quantity is never precomputable), the registry cards its board uses, and the golden
   items covering it. Seed from phase-39 items marked `precomputable`.
2. Target 30–50 intents. Record the share of golden items covered; aim for most of
   `today_state`, `product_faq` and common `knowledge_methodology`.

### B. The nightly answer packs
3. A `run_daily` step, after the context pack and before notarisation, generates for
   every (intent, pair, locale): speech text, resolved board spec, provenance records
   for every value, and a cache key. **All five gates run at build time**, so a pack
   that would fail a gate never exists and no gate work happens at request time.
4. **Audio is baked.** Synthesize each pack's speech with the production voice and
   store it beside the pack. At request time the avatar receives cached audio through
   the existing passthrough path, removing the largest latency component from the
   common path.
5. Manifest records `context_version`, `intent_version`, `registry_version`,
   **`prompt_version`, `gate_rules_version`, `model_id_and_version`, `voice_id`**,
   per-pack SHA-256, generated_at, total bytes. **A change to prompt version, gate
   rules, model or voice invalidates every pack** — the build must regenerate rather
   than serve content gated or spoken under superseded rules. Test this.
6. Determinism and cost: temperature 0, a hard per-night cap on model and TTS spend,
   and a line in the nightly summary.
7. **Staleness is explicit, never silent.** Packs carry the context date. If the
   nightly build failed, serving may use yesterday's packs but must attach the stale
   badge and auto-append the drift card. A test forces a failed build and asserts it.

### C. The rollup cube
8. A second nightly step writes `data/rollups.parquet`: counts and means by pair ×
   month × regime, regime run lengths, siren exceedances, event-window statistics, and
   the ledger scoreboard over standard windows. Document exactly which shapes are
   covered.
9. Phase-42's archive room queries the cube first and falls back to a live scan only
   for uncovered ranges. This removes the most likely source of a slow tail.
10. Cube values carry a provenance kind of their own, recording the rollup definition
    so any number traces back to its recipe.

### D. The intent classifier — leakage-free by construction
11. **Training corpus is separate from the eval set.** Build
    `data/intent_train.jsonl` from three sources: the phrasings authored in
    `config/intents.yaml`; paraphrases generated offline at build time by the model
    (10–20 per intent per locale — legitimate because they train *routing*, never
    numbers, and never touch the eval set); and confirmed items promoted from
    `reports/answer_gap_log.md`. **No golden item may enter training** — a test
    asserts the intersection of training and eval questions is empty.
12. Model: character n-gram TF-IDF into logistic regression, one model across all three
    locales, probabilities calibrated. sklearn-only, so it trains and tests inside the
    existing CI.
13. Evaluate on a **held-out split of the training corpus** for model selection, and
    report final accuracy **only on the golden set**, which the model has never seen.
    Publish both numbers in `reports/intent_classifier.md` — they will differ, and the
    gap is informative.
14. Choose the confidence threshold on the held-out split and publish the coverage
    versus precision curve. Never let a low-confidence classification select a pack.
15. **Drift monitoring:** export the confidence distribution as a histogram and alert
    when the low-confidence share rises beyond a threshold — that is the signal your
    users have started asking something new. Retrain whenever the golden set or the
    gap log grows materially; the artifact is versioned and rollback-able.

### E. Conversation state and reference resolution
16. Server-side session state, small and explicit: `last_intent`, `last_pair`,
    `last_date_range`, `last_board_cards`, `locale`, `turn_index`, with a short TTL and
    a hard reset on session end. Never store free text beyond what resolution needs.
17. **Resolution runs before classification.** A deterministic resolver expands
    elliptical utterances against state: bare pair names ("and USDCHF?", "und der
    Franken?") inherit the last intent; bare time expressions ("what about last
    month?") inherit the last intent and pair; pronouns and deictics ("that one", "the
    same for…") resolve to the last board's subject. If resolution is ambiguous, ask a
    one-line clarifying question rather than guessing — a wrong silent resolution is
    worse than a short question.
18. The resolved interpretation is **echoed in the answer** ("USDCHF, same reading —
    calm today") so the user can catch a mis-resolution immediately, and it is recorded
    in the trace.
19. Follow-up phrasing: packs carry two speech variants, `standalone` and `followup`,
    generated at build time. "USDCHF is calm today" versus "USDCHF is calmer, actually"
    — the second is what a person says when answering a follow-up, and the difference
    is most of what makes a voice product feel human rather than robotic.

### F. Serving and observability
20. Metrics: `answer_pack_hit_ratio`, `answer_pack_stale_total`,
    `intent_classifier_confidence` histogram, `intent_classifier_lowconf_ratio`,
    `reference_resolution_total{outcome}`, `rollup_hit_ratio`,
    `nightly_pack_build_seconds`, `nightly_pack_cost_chf`.
21. Latency histograms gain a `path` label (`pack|paraphrase|live`); report p50/p95/p99
    per path.
22. A pack answer and a live answer for the same question must be indistinguishable in
    wording style, board layout and disclosure — a test compares one of each.

## Do not
No precomputation of anything involving a user-supplied quantity, a scenario, or the
research lab. No serving a pack whose `context_version`, prompt version, gate version,
model or voice does not match current, without regeneration or the stale badge. No
golden item in the training corpus. No skipping build-time gates because the content is
"ours". No unbounded nightly cost. No silent reference resolution — always echo it. No
guessing when resolution is ambiguous.

## Verify
- Nightly build produces the full pack set with both speech variants and audio; show
  the manifest, size, wall-clock and cost.
- Golden set re-run: `answer_pack_hit_ratio` and p50/p95/p99 for the pack path against
  the phase-39 baseline — expect the common path to drop from about a second to tens of
  milliseconds plus audio start.
- Version-invalidation test: bump the gate-rules version and show every pack
  regenerating rather than serving.
- Forced-failure test: yesterday's packs serve with the stale badge and drift card.
- Training/eval disjointness test passes; `reports/intent_classifier.md` shows held-out
  accuracy, golden-set accuracy, the threshold curve and a per-locale confusion matrix.
- Multi-turn family: reference resolution accuracy reported; show three resolved
  follow-ups with the echo line, and one ambiguous case producing a clarifying question.
- Cube and live scan agree on a shared range; a pack answer and a live answer are
  indistinguishable side by side.
- `make test`, `make lint-ui` green; CI still ~5 minutes.
- CHANGELOG, commit `phase-40: precomputed answers, cube, classifier, conversation
  state`, next minor tag.

## Teach me
Explain: why a daily-cadence product should have daily-cadence answers, and what that
buys beyond speed; why baking the audio removes the largest latency component; why
training a router on the eval set invalidates its reported accuracy, and why generated
paraphrases are a legitimate substitute here; why an ambiguous reference deserves a
question rather than a guess. Quiz me: (1) the nightly build fails at 06:00 — what does
a user experience at 09:00, and why is that correct? (2) held-out accuracy is 96% but
golden-set accuracy is 81% — what does that gap tell you, and what do you do about it?
Critique my answers.
