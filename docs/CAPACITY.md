# Capacity

What the machine carries, what moved off it in phase 44, and what the freed headroom is reserved
for. Kept as a document rather than a dashboard because the numbers change on the scale of phases,
not minutes.

_Educational tool. Not investment advice._

## The machine

Oracle Cloud always-free ARM instance, CPU only. No GPU, and nothing in the serving path needs one:
the avatar's face renders in the vendor's cloud over WebRTC, and every model on this box is a small
CPU model exported to ONNX.

Record the live shape with `nproc` and `free -m` at deploy time and keep it here; the figures below
describe allocation, not the hardware's spec sheet.

## What the VM carries after phase 44

| workload | resident | notes |
|---|---|---|
| `fxradar-serve` (axum) | the bulk | engine, packs, indices, archive, avatar brain |
| Caddy | small | TLS termination and reverse proxy |
| SQLite | small | keys, transcripts, webhooks, usage, ops audit |
| ~~static page serving~~ | **moved to CDN** | the five customer pages and their assets |

The pipeline does **not** run here — it runs in GitHub Actions and commits artifacts, so training and
scoring never compete with serving for memory. That was a phase-03 decision and it is the reason
this box is comfortable.

## What moved off, and what it frees

The five customer pages, their CSS, the icons and `state.json` now publish to a CDN from the
repository on each artifact commit. In bytes this is small — the whole surface is under 100 KB — but
what actually moved is **the request volume**: every anonymous page view, every crawler, every
link-preview fetch. Those never reach the VM now.

Two consequences worth stating plainly:

1. **The proof page survives the VM.** Verifiability is this product's central claim, and hosting the
   evidence on the machine being vouched for was always the wrong shape. It now stays reachable when
   the API is down.
2. **The VM's load is now proportional to actual use** — avatar sessions, scenario pricing, alert
   management — rather than to attention. A link doing well on a Friday afternoon no longer touches
   the box at all.

## Headroom, and what it is reserved for

The freed memory is reserved for phase 45's concurrency work, specifically the DuckDB connection
pool and request queue in front of the archive room. That is the component whose sizing has to come
from measurement rather than a guess, and it is the one that will consume the headroom.

Nothing else should claim it in the meantime. Reserving headroom and then spending it on whatever
arrives next is the same as not reserving it.

## Known limits

- **The archive is a JSON document held in memory**, not a query engine. That is why it costs
  nothing per request and why its size is a start-up cost rather than a per-turn one — and it is
  also the limit: it answers eleven closed shapes and nothing else. The day it needs to answer an
  arbitrary range is the day an embedded engine earns its place, with the bounds and the pool that
  phase 45 specified for it.
- **One box, no redundancy.** A VM failure takes the API down until it restarts; see
  `docs/RUNBOOK.md`. The static surface is unaffected, which is most of what a reader needs.
- **The avatar's cost caps are monthly and enforced server-side**, so the ceiling on vendor spend is
  a configuration value rather than a hope.

## Measured, and where

`scripts/load_test.py` drives N concurrent sessions against a running service. Full tables in
`rust/BENCH.md`. **Run on an ARM Mac, not on the Oracle VM** — so these are not capacity figures for
the VM and are not presented as such.

| concurrent sessions | req/s | p50 | p95 | p99 | errors | resident |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 110 | 8.8 ms | 9.8 ms | 15.0 ms | 0 | 28 MB |
| 3 | 293 | 10.2 ms | 11.0 ms | 17.2 ms | 0 | 33 MB |
| 5 | 467 | 10.4 ms | 13.2 ms | 18.2 ms | 0 | 37 MB |
| 10 | 783 | 12.2 ms | 16.8 ms | 20.9 ms | 0 | 44 MB |

**19.8 MB at rest, 48 MB peak.** Two things transfer from this even though the absolute numbers do
not:

**Memory is the binding constraint, and it is paid up front.** The service loads its indices, packs
and archive once at start-up and holds them read-only, so resident memory is a function of the
artifacts rather than of concurrency — it moves 28 → 44 MB across a tenfold increase in load. On a
small box you run out of memory long before you run out of CPU, and you know your floor before the
first request arrives.

**Latency degrades smoothly, not off a cliff.** p50 rises 8.8 → 12.2 ms from 1 to 10 sessions with
zero errors. Nothing queues, nothing times out, and the deadline is never approached.

## The concurrency limit is not set

The phase asks for a limit derived from the point at which the deadline starts being missed. **This
host never got near it**, so there is no measurement to derive one from, and a limit taken from a
machine that never struggled would be a guess wearing a number. It has to come from the VM.

## What is not measured yet

- **Everything above, on the actual VM.** The shape is known; the numbers are not.
- **The saturation point** — the concurrency at which the deadline starts being missed — and
  therefore the concurrency limit and queue depth.
- **Sustained load over hours** rather than seconds, which is where memory growth would show if
  there is any.

A note on the DuckDB bounds this document was expected to carry: **there is no DuckDB.** Phase 42
measured the four hard families at 81–92% using eleven closed archive shapes and concluded that an
embedded query engine should not be built yet. The memory limits, thread counts, statement timeouts
and scan windows specified for it are therefore not applicable, and inventing figures for a component
that does not exist would make this document less useful, not more.
