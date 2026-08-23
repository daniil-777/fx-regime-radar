# How this system is measured

Everything after phase 39 is a comparison — faster, cheaper, more accurate than *what?* Without a
fixed measuring stick, "better" is taste wearing a lab coat. This document is the stick's operating
manual.

## The three rules

**1. Never evaluate against `data/`.** The daily pipeline rewrites it every weekday morning, so a
suite pointed there produces a different number each day for reasons that have nothing to do with
the code. Worse, the flakiness is indistinguishable from a regression, which is what makes it
expensive: you spend an afternoon debugging the market. Every eval path reads
`eval/snapshot/<label>/`, and `tests/test_eval_harness.py::test_no_eval_path_reads_live_data`
enforces it mechanically.

**2. Never type a gold value.** Each numeric expectation carries a `source_ref` — an address into
the snapshot — and the harness resolves it at load time. A typed number is correct exactly once;
after the next pipeline run it punishes a system that is right, and nobody notices for weeks because
a stale fixture and a real regression look identical from the outside. An unresolvable `source_ref`
fails the *build*, which costs a minute, rather than the *model*, which costs an afternoon.

**3. Never let a judge decide a number.** The LLM judge is bounded to phrasing and relevance. Every
number is decided by comparison against a resolved value, in the locale the question was asked in.
If the judge's agreement with human labels falls below κ 0.6 it is dropped from the report entirely
rather than quoted with a caveat nobody reads.

## Re-baselining: the rule that keeps comparisons honest

These fields are **pinned** in every report header:

`model` · `model_version` · `judge` · `prompt_version` · `gate_rules_version` · `registry_version` ·
`snapshot_hash` · `git_sha` · `seed`

**If any of them changes, previous results are no longer comparable and a fresh baseline is
required.** This is not bureaucracy. A model version change alters the generator's distribution:
numeric exactness can move several points with no code change at all, and a team that diffs across
that boundary will "discover" an improvement it did not make, or chase a regression that is a vendor
release. `python eval/run_eval.py --diff A B` refuses to subtract two reports whose pinned fields
differ, and prints which ones drifted.

Re-baseline by: rebuilding the snapshot if the data window is being moved, re-recording fixtures,
re-running the report, and committing it with a note saying *which pinned field changed and why*.

## What runs where

| | CI (every push) | Nightly |
|---|---|---|
| network / model | never | yes, real model |
| retrieval metrics | computed live from the snapshot's registry | same |
| routing, numeric, provenance | scored over **recorded fixtures** | scored over fresh answers |
| latency and cost | recorded values | measured, p50/p95/**p99** |
| judge | never | if a key is configured, with κ |
| runtime budget | well under two minutes | unbounded |

CI is hermetic by construction: it scores `eval/fixtures/responses.jsonl`, which was recorded once
against the snapshot. Re-record with `make eval-record` after any change to the answering path —
that is the moment fixtures go stale, and a stale fixture is a lie with a timestamp.

## The weekly triage

Two logs feed the golden set:

- `reports/visual_gap_log.md` — the assistant wanted a card that does not exist, or fell back to the
  catch-all when the question deserved better.
- `reports/answer_gap_log.md` — gate blocks, provenance failures, a user re-asking within two turns
  (the clearest signal an answer missed), and unresolved references in follow-ups.

Once a week, every entry is either **promoted into `eval/golden.yaml` as a new item** or **closed
with a written reason**. Nothing is left open without one of those two outcomes. The re-ask signal
deserves particular attention: users rarely complain, they just ask again, and that rephrasing is
the most honest bug report the system will ever receive.

## Running it

```bash
make eval-snapshot        # freeze today's artifacts (only when re-baselining)
make eval-record          # record fixtures against a service started on the snapshot
make eval-ci              # hermetic scoring, the CI gate
make eval-report          # write reports/eval_baseline.md
python eval/run_eval.py --diff reports/eval_baseline.md reports/eval_nightly.md
```

`eval/smoke_live.py` is the one exception to rule 1: three questions against live artifacts,
asserting only structure — a board rendered, gates passed, no exception — and never a value. It
catches "the pipeline wrote something unreadable this morning", which the snapshot by design cannot.
