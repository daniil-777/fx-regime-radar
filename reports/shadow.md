# Shadow mode — pre-registered, not yet run

_Phase 45. The criteria below were written **before** any shadow data existed, which is the only
state in which they mean anything._

_Educational tool. Not investment advice._

## Status

**Implemented and never run.** The flag (`shadow_mode`), the sampling rate (`shadow_sample_rate`,
default 0.2) and deterministic per-session bucketing all exist and are unit-tested. What does not
exist is real traffic. Nothing in `docs/AGENTIC_SEARCH.md` or `reports/ablation.md` rests on shadow
data, and this file contains no results because there are none.

## Why the criteria are written first

Once you have seen the data you can always find a threshold it clears. Writing the numbers down
beforehand is the difference between a decision and a rationalisation, and it costs nothing except
the discomfort of possibly failing your own test. That discomfort is the point.

## Pre-registered promotion criteria

Over **at least 200 real turns**, at a sampling rate recorded in the report:

| criterion | threshold |
|---|---|
| gain on `ledger_historical`, `multi_hop`, `aggregation`, `comparative_temporal` | **≥ 5 percentage points**, combined, against the served path |
| regression on `today_state` routing | **none** — any loss fails promotion outright |
| regression on `today_state` p95 time-to-first-word | **none beyond 10%** |
| provenance failures on the shadow path | **exactly zero** |
| added cost per turn | **within the configured per-day budget**, stated in CHF |
| adversarial families | **100% maintained**; a single leak fails promotion regardless of every other number |

The last row is not a threshold, it is a veto. No gain anywhere buys a direction leak.

## Sampling: why 20% and not everything

Shadowing every turn doubles model spend to learn what a sample answers just as well. At 20%, 200
turns arrive within a working week of modest traffic, and the confidence interval on a five-point
difference is comfortably inside what the criteria ask for.

Sampling is **deterministic in the session id**, not random per turn: a session is shadowed
throughout or not at all. Half a shadowed conversation measures nothing, because the agentic path
would be reasoning from a conversation state it never watched being built.

## What shadow tells you that the frozen snapshot cannot

The snapshot answers "is this correct on the questions we thought of". Shadow answers "is this
correct on the questions people ask" — and those differ in a specific, repeatable way: real questions
are shorter, more elliptical, more often mid-conversation, and far more often about something the
golden set has no item for. The golden set is written by someone who knows the system. Nobody using
it does.

It is also the only place where the cost column becomes real. The ablation cannot compute cost per
answer because it runs keyless; shadow runs against a live key by construction.

## Running it

```bash
curl -X POST $BASE/ops/flags -H "X-Ops-Key: $KEY" \
  -d '{"flag": "shadow_mode", "value": true}'
```

Effective on the next turn, no redeploy. Shadow work runs as a separate lower-priority task under its
own deadline, serves nothing, and is hard-cancelled when resources are tight — a measurement must
never delay the answer being measured against.

To stop: the same call with `false`, or pull `agent_enabled` and stop everything at once.
