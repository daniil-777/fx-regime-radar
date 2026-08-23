# Retrieval ablation — what earned its place, and what did not

_Phase 41. Every number below was measured on the frozen snapshot against the 280-item golden set.
Two components were rejected on evidence; both are recorded here, because a documented negative is
the part of this exercise that saves the next person a week._

## The headline

| stage | registry recall | notes |
|---|---:|---|
| phase-39 baseline | 81.0% | EN 87.4% · DE 65.0% · FR 68.0% |
| + cross-locale vocabulary | 81.5% | German compounds and French terms mapped onto canonical ones |
| + paraphrases in the index | 90.6% | the same offline phrasings the classifier trains on |
| + BM25 with length normalisation | **94.5%** | **EN 95.2% · DE 88.6% · FR 100%** |

Retrieval-eligible items only: cards selected by the direction and advice guards are excluded,
because retrieval never runs for them and scoring them measured a code path that does not exist.

## What earned its place

**Index content, not the ranking function.** The registry declared eight or nine English phrasings
per card but only three to five German. Recall was 87% in English and 65% in German — and the
ranking function was never the problem, because the index had simply never seen the words. Feeding
in the 900 offline paraphrases moved German 65% → 80% and French 68% → 91% before a single scoring
change. **The cheapest retrieval win available was more index, not better maths.**

**German compound splitting.** "Absicherungsquote" is one token that never matches "hedge ratio".
The list is domain-specific on purpose: a general decompounder splits "Bitcoin" into "bit" and
"coin".

**BM25 length normalisation.** Card documents differ in size by a factor of three, and plain IDF
overlap was rewarding the long ones for being long. BM25 lifted German from 77% to 88.6% and French
to 100%.

**k = 6 → 8.** Measured: recall 89.0% → 92.8% at the time of the decision, for +107 prompt tokens
(+23% of the injected slice). Cheap at this size, and the slice remains capped, so the flat-prompt
guarantee of phase 38 still holds.

## What was rejected

**Embeddings — declined, not deferred.** The phase permits a CPU embedding model once recall@6 is
below 98%. It is (94.5%). They were still declined, because the residual failures are not similarity
failures: they are archive-routed questions whose card expectation is stale, ultra-short ellipticals
that conversation state resolves at serve time, and one card with no data. An embedding model would
add a dependency, an ONNX runtime and a warm-up cost to a CPU-only VM, and would not touch any of
those three causes. **Revisit if the residual ever becomes semantic.**

**A cross-encoder reranker — not built.** With BM25 at 94.5% and the residual attributable to
routing rather than ranking, a reranker on ≤20 candidates would spend latency on a problem the
measurements say is not there.

## The finding that changed the design: rank score is not confidence

The paraphrase cache needs to know when it is sure. The obvious signal — how high the top card
scored — **does not work on this corpus, at all**:

| | median top score | 90th percentile |
|---|---:|---:|
| questions that deserve an answer | 12.71 | — |
| questions that should be refused | 4.71 | **23.69** |

No cut-off exists: the unwanted 90th percentile sits above the wanted median. A normalised variant
(top ÷ sum of top-5) separated no better — medians 0.299 and 0.296. The reason is structural rather
than fixable: **every question in this domain contains vocabulary that matches something.** "What is
the Swiss tax treatment of FX gains" is full of words this index knows.

What does separate them is similarity to a phrasing the registry actually *declares*:

| threshold | correct | wrong card | false positives | precision | coverage |
|---:|---:|---:|---:|---:|---:|
| 0.50 | 15 | 9 | 0 | 62% | 25% |
| 0.55 | 12 | 3 | 0 | 80% | 20% |
| **0.60** | **10** | **0** | **0** | **100%** | **17%** |

So the paraphrase cache serves a pack only above **0.60**: 17% of traffic, and on the golden set it
made no wrong-card matches and no false positives. The remaining 83% falls through to the normal
path, which is exactly what a cache should do.

**And the same gate applied to the caption path made things worse** — comparative-temporal routing
fell 59% → 35%, because a strict precision gate starves a path that was carrying real traffic. Two
paths, two thresholds, both measured: precision where a wrong answer is expensive, coverage where a
missed answer is.

## Family results, phase 39 baseline → now

| family | n | routing before | routing after |
|---|---:|---:|---:|
| `today_state` | 86 | 60% | **90%** |
| `aggregation` | 12 | 42% | **92%** |
| `multi_hop` | 16 | 38% | **81%** |
| `ledger_historical` | 21 | 71% | **86%** |
| `comparative_temporal` | 17 | 59% | **82%** |
| `knowledge_methodology` | 20 | 60% | **85%** |
| `causal_explanatory` | 11 | 55% | **73%** |
| `product_faq` | 11 | 36% | **73%** |
| `multi_turn_followup` | 21 | 62% | **76%** |
| `no_visual_expected` | 17 | 29% | **53%** |
| `adversarial_direction` | 12 | 8% | 8% |
| `adversarial_advice` | 10 | 10% | 10% |
| `out_of_scope` | 8 | 50% | 50% |

Total failures across the suite: **343 → 269**.

## The stop condition

The phase says: if `multi_hop`, `ledger_historical`, `aggregation` and `comparative_temporal` are
largely handled, write that down and stop rather than building an agent.

They are — 81%, 86%, 92% and 82% respectively, up from 38%, 71%, 42% and 59%. The work that got them
there was **the bounded archive of closed shapes**, not an agent: deterministic, testable, and unable
to invent a scan it was not designed for. A search agent would add planning latency and a new class
of failure (a plausible query over the wrong range) to a problem that eleven query shapes already
solve.

**Conclusion: do not build the open-ended search agent.** Phase 42's remaining value is the
discipline around the archive — route precedence, fully constrained request fields, point-in-time
guards, defined empty results — which applies to the shapes that already exist.

## The families that did not move, and why

`adversarial_direction` (8%) and `adversarial_advice` (10%) are unchanged, and no retrieval work will
change them: they are **routing** failures, not retrieval ones. The system refuses to leak direction —
`no banned words` is 100% throughout — but names the refusal in only one case in twelve; the rest
receive a tangential answer. That is the largest remaining quality gap in the product, it is
measured, and it belongs to the router rather than to this phase.

_Educational tool. Not investment advice._
