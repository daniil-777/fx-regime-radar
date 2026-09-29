---
description: Phase 45 — prove and ship: ablation, shadow mode, flags, capacity, rollback, runbook, and the public write-up (next minor tag)
---

Read CLAUDE.md golden rules first. Everything built in phases 39–44 now gets measured
against itself offline, then measured again against reality before it is trusted, then
released in a way that can be undone from a phone. The deliverable is one honest table
plus a short paper — simultaneously the strongest engineering artifact in the repo and
the thing to put in front of an interview panel hiring for retrieval systems.

## Step 0 — confirmed repo map (sanity-check, then confirm)
Pre-filled: phase-39 `eval/golden.yaml`, `eval/snapshot/`, `reports/eval_baseline.md`,
`make eval-ci`/`make eval-nightly`; phase-40 answer packs with baked audio, rollup
cube, intent classifier, per-path latency histograms; phase-41 indices, prompt cache
with prefix-hash alarm, paraphrase cache, `reports/retrieval_ablation.md`; phase-42
router, request slips, rooms, deadline, breakers, leakage probe, trace ids; phase-43
provenance records and `/ops/trace/{id}` with replay and promote-to-golden; phase-44
static surface with enforced budgets and `docs/RUNBOOK.md`; axum with API keys,
Prometheus, cost caps; Oracle VM (record shape, cores, RAM); CI sklearn-only ~5 min.
Verify, report drift, WAIT.

## Task
Run every configuration over the identical snapshot and golden set; run the agent in
shadow against real traffic without serving it; add per-lane flags and a kill switch;
measure capacity and memory on the actual VM; document and rehearse rollback; and
publish `docs/AGENTIC_SEARCH.md` with the results including the negative ones.

## Requirements

### A. The offline ablation
1. Run all of these against the SAME snapshot, golden set, seeds and judge config,
   varying one thing at a time: **A** phase-39 baseline · **B** +answer packs and cube
   (40) · **C** +BM25 hybrid (41) · **D** +contextual chunking · **E** +embeddings, if
   adopted · **F** +reranker, even though expected to be rejected — the number is the
   point · **G** +router and rooms (42) · **H** G with all caching disabled, to isolate
   the caching contribution; **I** G with conversation state disabled, to isolate what
   reference resolution contributes on the multi-turn family.
2. Every run records config hash, snapshot hash, registry, intent, prompt and
   gate-rules versions, model id **and version string**, voice id, judge id, and seeds.
   A result that cannot be reproduced from its header is not a result, and a report
   whose header differs from another on any pinned field **may not be diffed against
   it** — re-baseline instead. Enforce this with a check, not a convention.
3. Columns: registry recall@6 · knowledge recall@10 · route accuracy · numeric
   exactness · provenance coverage · coverage · adversarial refusal rate · p50/p95/**p99**
   time-to-first-word **per path** · tokens and CHF per answer. Rows A–H, with
   per-family and per-locale breakdowns beneath the headline table.
4. Add a **cost-of-quality** column: CHF per answer divided by the quality delta over
   baseline. This is what separates engineering judgment from feature enthusiasm, and
   it is what makes the reranker or the agent look defensible or absurd.
5. State sample size beside every metric and mark any difference you would not defend
   at n≈200. One- or two-point differences are noise.

### B. Shadow mode — measuring against reality
6. A `shadow` setting with a **configurable sampling rate** (default 20%, not 100% —
   shadowing every turn doubles model spend for a measurement that a sample answers
   just as well). Sampled turns are answered and served by the current production path
   while the agentic path runs concurrently under its own deadline, writes a full
   trace, and serves nothing. Record the sampling rate in every shadow report, and
   state the sample size beside every claim drawn from it. Shadow work must never delay the served
   answer — separate task, lower priority, hard-cancelled when resources are tight.
7. Nightly `reports/shadow.md`: agreement rate between paths, turns where the agent
   would have answered *better* (a family the packs cannot serve), turns where it
   would have been worse or slower, gate-trip differences, and added cost per turn.
8. **Promotion criteria, pre-registered before shadow starts:** over at least 200 real
   turns, a material gain on the historical, multi-hop and aggregation families; no
   regression on `today_state` accuracy or latency; zero provenance failures; cost per
   turn within budget. Write the thresholds down before looking at the data.

### C. Flags and the kill switch
9. Runtime-readable flags requiring no redeploy: `agent_enabled`, `lane_archive`,
   `lane_logbook`, `lane_cookbook`, `packs_enabled`, `paraphrase_cache_enabled`,
   `conversation_state_enabled`, `wait_line_enabled`, `embeddings_enabled`,
   `shadow_mode`, `shadow_sample_rate`. Each defaults safe.
10. A single kill switch (`agent_enabled=false`) returning the system to phase-41
    behaviour instantly, mid-session, without dropping active WebRTC sessions. Test it
    under load, not at rest.
11. Flag state exported as a gauge and stamped into every trace, so an old trace can be
    interpreted with the configuration that produced it.

### D. Capacity and memory on the real VM
12. Record the VM's actual cores and RAM, then measure and document in
    `docs/CAPACITY.md`: resident memory of the BM25 indices, the embedding model if
    adopted, DuckDB working memory under the heaviest whitelisted query, the answer-
    pack and audio footprint, the intent classifier, the DuckDB connection pool at its
    configured size, and the axum baseline. Set a hard total with headroom and
    fail the deploy if the sum exceeds it.
13. Bound DuckDB explicitly: `memory_limit`, `threads`, statement timeout, mandatory
    `LIMIT`, maximum scan window. An unbounded aggregation over years of parquet on a
    small box is the single most likely way this falls over.
14. Concurrency test with `oha` or `k6` against the real VM: 1, 3, 5 and 10 simultaneous
    sessions each issuing a slow-lane question, plus a pack-path load for contrast.
    Record p50/p95/p99 time-to-first-word, error rate, memory high-water mark, and the
    point at which the deadline starts being missed. Append to `rust/BENCH.md`.
15. From those numbers set a **concurrency limit** with a queue and a graceful "one
    moment" response beyond it — never let overload express itself as a timeout
    mid-sentence.
16. Index and pack builds never run on the serving VM during business hours: build in CI
    or the nightly window, ship the artifact, load read-only.

### E. Rollback and the runbook
17. Rollback ladder with expected recovery time per step, each executable from a phone
    in under two minutes: flip the affected lane flag → `agent_enabled=false` → revert
    to the previous tagged release → restore the previous index or pack artifact →
    repoint DNS to the Streamlit surface.
18. Every rollback-able artifact versioned and retained at least two weeks: index
    builds with manifests, answer packs, registry and intent versions, prompt versions,
    context packs.
19. Rehearse it: promote, then roll back mid-session, and show active sessions keep
    working and answers stay grounded.
20. `docs/RUNBOOK.md` extended, one page, written for yourself at 2 a.m.: symptom →
    likely cause → first action, covering rising p95 (cache hit ratio, prefix hash,
    per-stage histogram), a breaker stuck open (DuckDB memory, snapshot read path),
    provenance failures appearing (did the nightly pack build?), cost spiking (cache
    ratios, tool-round distribution), the daily Action failing (stale badge should
    already show), and "answers sound wrong but gates pass" (open the trace, replay,
    promote to golden). Every entry names the metric that proves the diagnosis and the
    flag that mitigates it.

### F. Failure analysis and the write-up
21. Root-cause the ten worst remaining failures into exactly one of: retrieval miss,
    routing error, generation error, gate block (correct or incorrect), missing data.
    Publish the distribution — it is the roadmap for whatever comes next. For each,
    name the cheapest fix and whether you took it; "not worth fixing, because…" is a
    legitimate and senior entry.
22. `docs/AGENTIC_SEARCH.md` for a technical reader who has never seen the project: the
    problem (a voice assistant over daily financial artifacts, one-second budget, no
    hallucinated numbers); the architecture in one page; the safety invariant (the model
    emits keys, never values; the schema contains no numeric type); the point-in-time
    guarantee and why the sealed ledger makes it verifiable rather than promised; the
    precomputation decision and what it bought; the results table; **the negative
    results, led not buried**; the limitations; and a reproduction recipe (clone,
    `make build-index`, `make eval-nightly`) plus a short "what I would do at ten times
    the traffic" paragraph.
23. Link it from the README top and the proof page. Add one line to the public metrics
    page carrying the same claim as the paper.
24. Wire the ablation into the nightly job so the table regenerates and drift is visible.

## Do not
Do not vary two things between runs. Do not report a metric without its sample size. Do
not omit a configuration because it embarrassed an earlier decision. Do not present
judge scores as evidence about numbers. Do not promote out of shadow without the
pre-registered numbers. Do not ship a flag that needs a redeploy. Do not leave any
DuckDB query, thread count or scan window unbounded. Do not claim a capacity figure you
did not measure on the actual VM. Do not document a rollback you have never executed.

## Verify
- `reports/ablation.md` with all eight configurations, full breakdowns, reproducible
  headers, and the cost-of-quality column.
- Shadow run over a full day; `reports/shadow.md` with agreement rate, where the agent
  wins, cost delta — and a plain statement of whether promotion criteria are met.
- Kill switch demonstrated mid-session under load; sessions survive.
- `docs/CAPACITY.md` with measured figures; deploy fails when the budget is exceeded
  (show it failing); concurrency table in `rust/BENCH.md` with the limit set from data.
- Rollback executed for real and timed; runbook reviewed line by line — I will pick two
  entries at random and you will walk me through executing them.
- `docs/AGENTIC_SEARCH.md` read as a skeptical interviewer; reproduction recipe
  executed from a clean clone reproduces the table.
- `make test`, `make lint-ui` green; CI still ~5 minutes.
- CHANGELOG, commit `phase-45: prove and ship`, next minor tag.

## Teach me
Explain: why an ablation varying one thing at a time is worth more than a better final
number; why cost-of-quality is the column that reveals judgment; why shadow mode tells
you something the frozen snapshot never can; why promotion criteria must be written
before the data is seen; why memory rather than CPU is the binding constraint on a small
VM; why a rollback never executed is not a rollback. Then rehearse me: play a
retrieval-systems interviewer and ask the three hardest questions — how the
no-hallucinated-number guarantee survives tool use, when the agent is worse than the
precomputed path and how I prevent that regression, and how I prove a historical answer
contains no hindsight. Push back twice on each, then tell me which one I still cannot
defend.
