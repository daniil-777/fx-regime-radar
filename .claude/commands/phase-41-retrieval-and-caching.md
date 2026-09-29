---
description: Phase 41 — hybrid retrieval for the tail, contextual chunking, prompt and paraphrase caching, warm-up on restart (next minor tag)
---

Read CLAUDE.md golden rules first. Phase 40 took the common path off the request and
gave follow-ups a memory. This phase makes the remaining traffic — paraphrases the
classifier missed, the long tail, questions nobody anticipated — find the right card
and the right paragraph reliably, and stops the system re-reading the same
instructions on every call. If the numbers afterwards show the hard families are
handled, the honest move is to stop and never build the agent.

## Step 0 — confirmed repo map (sanity-check, then confirm)
Pre-filled: phase-39 harness with computed gold values and pinned-version rule;
phase-40 intents, packs with both speech variants and baked audio, rollup cube, intent
classifier with drift monitoring, conversation state and reference resolution, `path`
label on latency histograms; registry `config/visual_registry.yaml` with per-card
`question_intents` in EN/DE/FR; knowledge `docs/avatar_knowledge.md`,
`docs/hedging_knowledge.md`, storm reports; the brain assembles [tools][system
prompt][knowledge][context pack][retrieved slice][question] for Haiku; CPU-only VM; CI
sklearn-only ~5 minutes. Verify, report drift, WAIT.

## Task
Build two indices with lexical-first hybrid retrieval and rank fusion; add contextual
chunking; restructure the prompt so its stable prefix is cacheable; add a paraphrase
cache mapping near-miss questions onto existing packs; warm everything on restart;
then re-run the golden set and publish the delta.

## Requirements

### A. Indices — lexical first, embeddings only if measurements demand it
1. BM25 indices with per-language analysers (EN/DE/FR stemming; German compound
   handling matters — "Wechselkursrisiko" must match "Wechselkurs"). Two indices:
   `idx_registry` over card intents plus a one-line gloss, and `idx_knowledge` over
   document chunks.
2. Measure recall@6 on the registry and recall@k on knowledge. **Only if registry
   recall@6 < 98%**, add a small CPU embedding model — one multilingual model rather
   than three monolingual pipelines — ONNX INT8, installed via
   `requirements-ml-ext.txt` on the VM, never in CI. Publish before and after.
3. Fuse lexical and dense ranks with Reciprocal Rank Fusion (k=60). No score
   normalisation, no tuned weights.
4. **Fallback if 98% still cannot be reached:** raise k from 6 to 8, measure the added
   prompt tokens and latency, and if the trade is unfavourable, always include the two
   catch-alls and accept a documented lower target. Decide by measurement and write the
   decision down; do not leave the target aspirational.
5. Evaluate a cross-encoder reranker over at most 20 candidates and **expect to reject
   it**. Record the number either way in `reports/retrieval_ablation.md` — a documented
   negative is a deliverable.

### B. Contextual chunking
6. Chunk knowledge docs on heading boundaries with target size and overlap, then
   prepend a one-line, generated-once context sentence naming document, section and
   subject. Generate offline at index-build time, store enriched, hash it.
7. `make build-index` writes `data/index/` with a manifest of source hashes, chunker
   version and model ids. CI asserts a rebuild reproduces the committed manifest.

### C. Prompt caching
8. Ordered prefix: `[tool schema] → [system prompt] → [knowledge pack] → [today's
   context pack]`, cache breakpoint, then `[retrieved slice] → [resolved conversation
   state] → [question]`. Nothing volatile before the breakpoint.
9. **Prefix-drift alarm.** Log a SHA-256 of the cacheable prefix on every request and
   export `prompt_prefix_hash_changes_total`. A silent cache miss is indistinguishable
   from a hit except in the bill and the tail.
10. Export `prompt_cache_hit_ratio`; alert below a threshold.

### D. The paraphrase cache
11. Normalise the question (lowercase, strip fillers, apply phase-40 reference
    resolution first), then find a near neighbour among intent phrasings above a
    similarity threshold **within the same `context_version`, locale and pinned
    versions**. On a hit, serve the existing pack — audio and follow-up variant
    included — with no model call.
12. Cache key includes `context_version`, `intent_version`, `registry_version`,
    `prompt_version`, `gate_rules_version`, `locale` and the prefix hash. Any nightly
    rebuild or version bump empties it. Never map a question carrying a user-supplied
    quantity onto a pack, and never cache a refusal-path answer.
13. Log every paraphrase hit with the original question for collision auditing; a test
    asserts EURUSD and EURCHF can never collide.

### E. Warm-up and cold-path handling
14. On service start and after any deploy or restart: load indices, load the classifier,
    prime the prompt cache with one throwaway request, and preload the ten most-served
    packs and their audio. Export `warmup_seconds` and refuse traffic (health check
    unready) until warm-up completes, so no user ever pays for a cold start.
15. Nightly, after the pipeline: re-warm automatically, since the pack rebuild
    invalidates everything.

### F. Correctness details that bite otherwise
16. Latency histograms keep the `path` label; add `paraphrase`. Report p50/p95/p99 per
    path.
17. Resolve relative expressions server-side in one declared timezone and echo the
    resolved absolute dates. Format numbers per locale while keeping tabular numerals.
    Tests for a French decimal, a German compound and a relative date crossing a
    weekend.
18. Pin the index snapshot hash into every eval run.

### G. Measure, then decide
19. Publish `reports/retrieval_ablation.md`: baseline → +packs and cube (40) → +BM25
    hybrid → +contextual chunking → (+embeddings) → (+reranker), with recall@6,
    knowledge recall, numeric exactness, coverage, reference-resolution accuracy,
    p50/p95/p99 per path, and cost per answer, broken out by family and locale.
20. **The stop condition.** If `multi_hop`, `ledger_historical`, `aggregation` and
    `comparative_temporal` still fail badly, proceed to phase 42. If they are largely
    handled, write that conclusion and stop.

## Do not
No embeddings before BM25 is measured. No reranker on the critical path. No tuned
fusion weights. No volatile content in the cacheable prefix. No paraphrase mapping for
questions with user quantities. No index built outside `make build-index`. No heavy
dependencies in CI. No serving traffic before warm-up completes. No aggregate-only
results.

## Verify
- `reports/retrieval_ablation.md` with the full table; state which components earned
  their place and which were rejected.
- Registry recall@6 ≥ 98% overall and ≥ 95% per locale, or the documented fallback
  decision with its measurements.
- Prefix-hash alarm demonstrated by changing one character of the system prompt; cache
  hit ratio across a simulated ten-question session.
- Paraphrase cache serves a German paraphrase of an English-authored intent from the
  pack, with audio, inside the pack-path budget.
- Restart the service and show `warmup_seconds`, the unready health check during
  warm-up, and that the first real request hits a warm cache.
- Collision, relative-date and locale-format tests pass; index rebuild reproduces the
  manifest byte-for-byte.
- `make test`, `make lint-ui` green; CI still ~5 minutes.
- CHANGELOG, commit `phase-41: hybrid retrieval + caching`, next minor tag.

## Teach me
Explain: why lexical retrieval often beats embeddings on a small domain corpus full of
names, codes and dates; what RRF does and why it needs no calibration; why one
character of prompt drift destroys the cache; why refusing traffic during warm-up is
better than serving a slow first request. Quiz me: (1) recall@6 is 99% in English and
88% in French — three most likely causes, in order? (2) cost per answer did not fall
after enabling caching — what do you check first? Critique my answers.
