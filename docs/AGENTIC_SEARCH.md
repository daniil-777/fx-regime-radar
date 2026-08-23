# Answering questions over financial artifacts without inventing numbers

_A voice assistant sits on top of a daily quantitative pipeline. It has about a second to start
speaking, it must never state a number the pipeline did not publish, and it must never say which way
a price is going. This is what that took, what worked, and — at more length than is comfortable —
what did not._

_Educational tool. Not investment advice._

---

## The problem

FX Regime Radar computes, once a day, a market-regime label for 23 currency pairs, a five-day
probability that the regime changes, a conformal interval on that probability, an anomaly percentile,
and a three-model consensus. Everything is written to committed artifacts and to an append-only,
hash-chained ledger that seals each forecast **before** its outcome is known.

The assistant reads those artifacts aloud. Three constraints shape every decision below:

1. **No invented numbers.** Every figure spoken must exist in a published artifact.
2. **No price direction, ever.** Not stated, not implied, not smuggled in as a ranking or a chart
   extrapolation. This is a constitutional rule, not a preference.
3. **About a second to first word.** A voice product that pauses has already lost the conversation.

The interesting part is that these three pull against each other. The safest system answers nothing.
The fastest system precomputes everything and cannot handle a question nobody anticipated. The most
capable system reasons freely and is exactly the one that will one day say "EUR/USD looks like it
will rise."

---

## Architecture in one page

```
GitHub Actions, 06:00 UTC          Rust service (axum, CPU-only VM)      Browser
─────────────────────────          ────────────────────────────────      ───────
prices → features → HMM      ┐     resolve references                    baked HTML
  → forecaster → siren       │     ↓                                     + WebRTC avatar
  → consensus → conformal    ├──►  topic guards (two layers)             + source chips
  → treasury → ledger        │     ↓                                     + receipts
  → context pack             │     archive room (bounded shapes)
  → answer packs + audio     │     ↓
  → rollup cube              │     answer packs / paraphrase cache
  → archive                  │     ↓
  → retrieval index          │     FAQ → cards → model (last resort)
  → public/state.json        ┘     ↓
                                   five output gates
                                   ↓
                                   provenance-stamped answer
```

Python trains and exports; Rust serves and imports nothing from Python at runtime. The only things
crossing are versioned artifacts with hashed manifests.

---

## The safety invariant

**The model emits keys, never values.**

When the assistant needs data it does not submit a query — it submits a *request slip* whose every
field is an enum or a pattern-validated string. There is no numeric type anywhere in the schema, and
a numeric-looking string is rejected by validation rather than coerced. A test asserts this
explicitly with `"14"`, `"1e3"` and `"0.68"` as inputs, because a model that cannot emit the integer
14 can still try to emit the string.

This matters more than it first appears. A model that can write SQL can write SQL that *runs* and is
*wrong*: correct syntax, wrong window, plausible number, no error anywhere in the system. A slip can
only ever be **unavailable**, and unavailable is a case the server answers rather than a mistake it
commits.

On top of that sit five output gates, applied to every answer before it reaches audio: topic guard,
direction lint, numeric grounding (every number must appear in the context pack), visual resolution,
and provenance. The numeric-grounding gate is the strongest guarantee in the system, and it holds
regardless of how the answer was produced — which is why a failure of the *input* guard shows up as
a bad answer rather than a false number.

### Point-in-time, and why it is verifiable rather than promised

Every archive query carries an `as_of` and the server applies `WHERE artifact_date <= as_of`
unconditionally. But the stronger guarantee is structural: the ledger is sealed before outcomes
exist, and it is hash-chained, so a historical answer cannot contain hindsight without breaking
every hash after it. A reader does not have to trust the claim — they can recompute the chain from
the published file and compare the head. That is a different kind of assurance from "we were
careful with our backtest", and it is the reason the proof page is served from a CDN rather than
from the machine being vouched for.

---

## What we built, in the order the measurements demanded

### Precompute the common path (phase 40)

The market moves once a day, so the answers should be built once a day. Every anticipatable question
is answered overnight — speech text, resolved board, provenance, **and synthesized audio** — with all
five gates run at build time. A pack that would fail a gate never exists.

Baking the audio is the single largest latency win available, because speech synthesis, not
inference, dominates time-to-first-word on the common path.

### Lexical retrieval, and the embedding model we declined (phase 41)

Registry recall started at 81% (English 87%, German 65%). The instinct is to reach for embeddings.
The measurement said otherwise: **the ranking function was never the problem — the index had simply
never seen the words.** Feeding in offline-generated paraphrases moved German 65% → 80% before a
single scoring change. BM25 with length normalisation took the total to 94.5%.

Embeddings were then **declined, not deferred**: the residual failures were routing errors, stale
card expectations and one card with no data. An embedding model would have added an ONNX runtime and
a warm-up cost to a CPU-only box and touched none of those three causes. A cross-encoder reranker was
not built for the same reason.

### The finding that changed a design: rank score is not confidence

The paraphrase cache needs to know when it is sure. The obvious signal — how high the top card
scored — **does not work on this corpus at all**:

| | median top score | 90th percentile |
|---|---:|---:|
| questions that deserve an answer | 12.71 | — |
| questions that should be refused | 4.71 | **23.69** |

No cut-off exists; the unwanted 90th percentile sits above the wanted median. The reason is
structural: **every question in this domain contains vocabulary that matches something.** "What is
the Swiss tax treatment of FX gains" is full of words this index knows.

What separates them is similarity to a phrasing the registry actually *declares*. At a 0.60
threshold that is 100% precise on the golden set at 17% coverage — and the same gate applied to a
different path made things worse, so the two paths carry two thresholds, both measured.

### A bounded archive instead of a search agent (phase 42)

The phase plan permitted an open-ended search agent. The measurements said not to build it: the four
hard families were already at 81–92% via eleven closed query shapes. An agent would have added
planning latency and a new failure class — a plausible query over the wrong window — to a problem
that was already solved. **The negative result is the deliverable.**

---

## Results

Measured on a frozen snapshot against a 280-item golden set whose gold values are *computed from the
snapshot*, never typed by hand. Hermetic, no network, reproducible from the header.

### Routing accuracy by family

| family | n | phase-39 baseline | now |
|---|---:|---:|---:|
| `today_state` | 86 | 60% | **92%** |
| `aggregation` | 12 | 42% | **92%** |
| `multi_hop` | 16 | 38% | **88%** |
| `comparative_temporal` | 17 | 59% | **88%** |
| `ledger_historical` | 21 | 71% | **86%** |
| `multi_turn_followup` | 21 | 62% | **86%** |
| `knowledge_methodology` | 20 | 60% | **85%** |
| `causal_explanatory` | 11 | 55% | **82%** |
| `no_visual_expected` | 17 | 29% | **82%** |
| `adversarial_injection` | 10 | — | **80%** |
| `product_faq` | 11 | 36% | **73%** |
| `adversarial_direction` | 12 | 8% | **100%** |
| `adversarial_advice` | 10 | 10% | **100%** |

Per locale: English 87%, German 82%, French 87%. Total failures across all metrics: 343 → **212**.

`no banned words` is **100% in every configuration and at every stage of this project**, before and
after every change above.

### The ablation: what each component is worth

Subtractive — start from the shipped configuration, turn one thing off, keep everything else
identical. Full table in `reports/ablation.md`.

| config | routing | four hard families | failures |
|---|---:|---:|---:|
| shipped | 86% | 88% | 212 |
| − answer packs | 86% | 88% | 212 |
| − paraphrase cache | 86% | 88% | 212 |
| − conversation state | 85% | 88% | 223 |
| − archive room | 84% | 83% | 217 |

**Conversation state is worth 11 failures; the archive room is worth 5.** The packs and the
paraphrase cache move nothing — and that is the correct result, not a verdict against them. They
exist to remove the model call from the common path; they are latency and spend optimisations, and
an accuracy ablation is the wrong instrument. Reporting "no measurable contribution" without that
sentence would be true and misleading.

---

## The negative results, led rather than buried

**1. We nearly shipped a compliance guarantee that did not hold in any real conversation.**

`adversarial_direction` sat at 8% and `adversarial_advice` at 10%. Not leak rates — nothing
directional was ever spoken, because the output gates are independent of the input guard. Those were
the rates at which the system *named the refusal*. Nine in ten direction questions got a fluent,
on-topic, entirely non-directional answer to a question the user had not asked.

Two causes. The keyword guard could not see through the costumes people actually use — embedded
premise, sentence completion, persona shift, chart extrapolation, authority claim. And worse:
**reference resolution was laundering direction questions.** "Will EURUSD rise?" was refused
correctly as the first turn of a session and *answered* as the second, because the resolver saw a
pair name, treated the utterance as elliptical, and rewrote it to the previous intent — discarding
the words that made it a direction question before the guard could see them. Every existing test
asked its adversarial question first in a session, so the suite was green while the guarantee did not
hold in any conversation with more than one turn.

Both are fixed and both families are now at 100%. The lesson generalises past this project: **a
guarantee tested only in the easy position is not tested.**

**2. The evaluation harness was under-measuring the system it evaluated.**

The multi-turn family sends a prior turn and then an elliptical follow-up. The recorder sent both in
a single request against a fresh session — but reference resolution reads *server-side* state keyed
by session id, which is empty on a session's first request. So the prior turn sat in an array the
deterministic path never reads, and the multi-turn family measured everything about the system
except the feature it exists to test.

The ablation found it: turning conversation state off changed nothing at all, which is only possible
if it was never on. Fixing the recorder moved multi-turn routing 76% → 81% and numeric exactness
19% → 32% **with no change to the system** — the system had always been better than its own
scoreboard said.

**3. An over-correction, caught by the same eval.**

Widening the direction vocabulary came within one commit of refusing "is volatility falling?" — a
question this product exists to answer. The fix is a proximity rule: a movement word is directional
only when it is not attached to a quantity we publish. A first attempt scanned the whole sentence,
which let "risk jumped on cable — so sterling weaker this week?" excuse itself using the word in its
premise. **A guard that refuses the product's own subject matter fails in the way nobody reports,
because the user simply leaves.**

**4. Normalisation that removed evidence.**

De-obfuscation (`1gn0r3` → `ignore`) maps digits to letters — so "800,000 EUR" became "8oo,ooo eur"
and "a 3% drop" became "a e% drop", and the exemptions that depended on that evidence silently
stopped applying on the normalised pass. The rule that came out of it: **normalisation may reveal an
obfuscated word; it may never remove evidence.** Exemptions are now decided once, on the original.

**5. An exemption granted with nothing behind it.**

A stated exposure ("we owe 800,000 EUR in three months") seemed like it should turn "should we hedge
or wait?" from a trade-timing question into a risk-management one. It does — but with the advice flag
off there is no decision engine to route it to, so the exemption produced no refusal *and* no answer:
one such question came back with an unrelated paragraph about the pipeline. The exemption list is now
empty, kept in the code as the hook for the day advice mode ships. **An exemption is only worth
granting when something real is waiting on the other side of it.**

---

## Limitations

- **`out_of_scope` sits at 50%** and `product_faq` at 73%. Both are measured, both are in the gap
  log, neither is a constitutional guarantee.
- **Ten archive coverage gaps remain** — "CHF risk vs a month ago", "what is the Brier since you went
  live", "how many days to the next policy meeting". The data exists; no query shape matches. The
  cheapest fix is more shapes, and it was not taken in this phase: each needs golden items first,
  and shipping shapes without them is how a bounded archive stops being bounded.
- **Shadow mode is implemented and has never been run.** The flag, the deterministic per-session
  sampling and the pre-registered promotion criteria all exist (`reports/shadow.md`); real traffic
  does not. Nothing in this document rests on shadow data.
- **Capacity figures are from a laptop, not the target VM.** 783 req/s at 10 concurrent sessions,
  p99 21 ms, zero errors, 48 MB resident — on an ARM Mac. The shape transfers; the absolute numbers
  do not, and `docs/CAPACITY.md` records what is still owed.
- **The judge metric is not run.** LLM-as-judge was specified with a Cohen's κ validation gate; that
  validation has not been performed, so no judge number appears anywhere here.
- **The framing rule set is incomplete by construction.** It catches the costumes someone thought of.
  It is a second line; the output gates, which do not depend on recognising the question at all,
  remain the actual guarantee.

---

## Reproduction

```bash
git clone <repo> && cd fx-regime-radar
python -m venv .venv && .venv/bin/pip install -r requirements.txt
make build-index                      # rebuild retrieval indices; manifest must match
cargo build --release --manifest-path rust/fxradar-serve/Cargo.toml

# serve the FROZEN snapshot, not live data
FXRADAR_AVATAR=on FXRADAR_AVATAR_DEV=1 FXRADAR_AVATAR_BRAIN_TOKEN=t FXRADAR_OPS_KEY=k \
  ./rust/fxradar-serve/target/release/fxradar-serve \
  --bind 127.0.0.1:8791 --data-dir eval/snapshot/<date>/data &

.venv/bin/python eval/record_fixtures.py --base http://localhost:8791 --verify-snapshot
.venv/bin/python eval/run_eval.py --out reports/eval.md          # the results table
.venv/bin/python scripts/run_ablation.py --base http://localhost:8791 --ops-key k
```

Every row of the ablation names its config hash; writing those flags and re-recording reproduces it.
`make eval-ci` runs the hermetic subset in under two minutes with no network and no model.

---

## At ten times the traffic

Memory, not CPU, is the binding constraint: the service loads its indices, packs and archive once and
holds them read-only, so the floor is paid before the first request and barely moves between 1 and 10
concurrent sessions. Ten times the traffic is therefore mostly a horizontal problem — the service is
stateless apart from a short-TTL conversation map, so it shards by session id behind any load
balancer, and the artifacts are identical read-only files on every node.

Three things would need actual work. **Conversation state** would move out of process, which is the
only genuinely stateful component. **The nightly pack build** would need to fan out, since it is
serial per (intent × pair × locale) and already the longest job. And **the archive** would stop being
a JSON file loaded into memory — at ten times the traffic the case for a real embedded query engine
finally arrives, along with the connection pool, queue and memory bounds this phase specified for a
DuckDB layer that measurements said not to build yet.

What would not change is the shape: precompute what is anticipatable, serve it without a model, and
keep the model on the tail where it earns its latency.
