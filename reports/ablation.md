# Ablation — what each component is worth

_Phase 45. Every row ran over the identical frozen snapshot, the identical 280-item golden
set and the identical seeds, with the service never restarted between rows. Exactly one
flag differs per row, always from the shipped configuration._

**Subtractive, not cumulative.** The rows below turn one component *off* rather than
building up from a baseline. That answers the question anyone actually acts on — what is
this component worth now, and could it be deleted — measured against the system as it
exists. The cumulative retrieval ladder (BM25, contextual chunking, embeddings, reranker)
was measured in phase 41 and is carried forward below rather than re-derived; those
components are not behind flags, and two of them were declined and never built.

## Headline

| config | change | routing, all 280 | the four hard families | today_state | constitutional | failures | p50 | p95 | p99 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `S` | shipped | 86% | 88% | 92% | 100% | 212 | 4 ms | 11 ms | 14 ms |
| `−packs` | no precomputed answers | 86% | 88% | 92% | 100% | 212 | 4 ms | 6 ms | 10 ms |
| `−cache` | no paraphrase cache | 86% | 88% | 92% | 100% | 212 | 4 ms | 11 ms | 12 ms |
| `−state` | no conversation state | 85% | 88% | 90% | 100% | 223 | 4 ms | 11 ms | 11 ms |
| `−rooms` | no archive room | 84% | 83% | 90% | 100% | 217 | 4 ms | 11 ms | 11 ms |
| `kill` | kill switch pulled | 84% | 83% | 90% | 100% | 217 | 4 ms | 10 ms | 11 ms |

**The latency columns are server-side and keyless.** No `ANTHROPIC_API_KEY` was present
at record time, so every row answers from deterministic paths and none of them calls a
model. Single-digit milliseconds is what the archive, the packs and the board selector
cost — it is *not* the production picture, where time-to-first-word is dominated by the
model call and by speech synthesis on the paths that reach them. `−packs` reads slightly
faster here for the mundane reason that a pack lookup costs a few milliseconds and the
fallback path it avoids is already fast when no model is in it. Under a live key that
ordering inverts, which is the entire reason the packs exist.


Sample sizes: 280 items overall; the four hard families are 66 items between them; today_state is 86; the two constitutional families are 22.
**A one- or two-point difference on a family of ten or twenty items is noise and is not
defended here.** Differences worth reading are called out in the prose below.

## Per family

| family | n | `S` | `−packs` | `−cache` | `−state` | `−rooms` | `kill` |
|---|---:|---:|---:|---:|---:|---:|---:|
| `today_state` | 86 | 92% | 92% | 92% | 90% | 90% | 90% |
| `knowledge_methodology` | 20 | 85% | 85% | 85% | 85% | 85% | 85% |
| `multi_hop` | 16 | 88% | 88% | 88% | 88% | 88% | 88% |
| `ledger_historical` | 21 | 86% | 86% | 86% | 86% | 81% | 81% |
| `aggregation` | 12 | 92% | 92% | 92% | 92% | 83% | 83% |
| `comparative_temporal` | 17 | 88% | 88% | 88% | 88% | 82% | 82% |
| `causal_explanatory` | 11 | 82% | 82% | 82% | 82% | 82% | 82% |
| `product_faq` | 11 | 73% | 73% | 73% | 73% | 73% | 73% |
| `multi_turn_followup` | 21 | 86% | 86% | 86% | 81% | 86% | 86% |
| `no_visual_expected` | 17 | 82% | 82% | 82% | 82% | 82% | 82% |
| `adversarial_direction` | 12 | 100% | 100% | 100% | 100% | 100% | 100% |
| `adversarial_advice` | 10 | 100% | 100% | 100% | 100% | 100% | 100% |
| `adversarial_injection` | 10 | 80% | 80% | 80% | 80% | 80% | 80% |
| `out_of_scope` | 8 | 50% | 50% | 50% | 50% | 38% | 38% |
| `stale_context` | 5 | 60% | 60% | 60% | 60% | 60% | 60% |
| `planted_number` | 3 | 33% | 33% | 33% | 33% | 33% | 33% |

## Per locale

| locale | `S` | `−packs` | `−cache` | `−state` | `−rooms` | `kill` |
|---|---:|---:|---:|---:|---:|---:|
| en | 87% | 87% | 87% | 87% | 84% | 84% |
| de | 82% | 82% | 82% | 80% | 82% | 82% |
| fr | 87% | 87% | 87% | 81% | 87% | 87% |

## Cost of quality

The phase asks for CHF per answer divided by the quality delta over baseline — the column
that separates engineering judgment from feature enthusiasm. **It cannot be computed from
this run, and a number here would be fabricated.** Every row above was recorded against
the frozen snapshot with no `ANTHROPIC_API_KEY` present, so the model was never called:
model cost per answer is exactly zero in all six configurations, and dividing zero by a
quality delta says nothing about anything.

What the run does show is the shape the cost column would take. Two components moved no
accuracy metric at all:

- **`−packs`** (no precomputed answers): identical on every family, 212 failures against the shipped 212.
- **`−cache`** (no paraphrase cache): identical on every family, 212 failures against the shipped 212.

That is not a verdict against them, and reading it as one would be the mistake this
table exists to prevent. The answer packs and the paraphrase cache were built to remove
the model call from the common path — they are latency and spend optimisations, and an
accuracy ablation is the wrong instrument for them. On this keyless snapshot every path is
already deterministic and fast, so the axis they operate on is flat by construction here.
Their real number is model calls avoided per hundred turns against a live key, which needs
the shadow run in `reports/shadow.md` and has not been performed.

**Reporting them as 'no measurable contribution' without that sentence would be the kind of
true-but-misleading result this whole document is meant to avoid.**


## Configurations

| config | flag changed | config hash | what it isolates |
|---|---|---|---|
| `S` | _none (shipped)_ | `e9557386` | everything on: packs, paraphrase cache, conversation state, the archive room |
| `−packs` | `packs_enabled=False` | `a15ac03f` | phase 40's nightly answer packs off; the live path serves everything |
| `−cache` | `paraphrase_cache_enabled=False` | `0f2ce5f2` | phase 41's near-miss matching off; a paraphrase falls through to the normal path |
| `−state` | `conversation_state_enabled=False` | `bcbaf275` | phase 40's reference resolution off; an elliptical follow-up is classified verbatim |
| `−rooms` | `lane_archive=False` | `226b22b6` | phase 42's bounded archive off; historical and aggregation questions have no source |
| `kill` | `agent_enabled=False` | `8e34b6ca` | the single switch an operator pulls at 2 a.m.: back to phase-41 behaviour |

_Every row is reproducible from its config hash: write the flags, re-record against the
frozen snapshot, score. `scripts/run_ablation.py` does exactly that and nothing else._


_Educational tool. Not investment advice._
