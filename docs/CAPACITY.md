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

- **DuckDB serialises** on a bounded thread pool. Concurrent archive queries queue, and the queue
  wait counts against the turn's deadline rather than hiding behind it. Pool size and queue depth
  are phase-45 measurements.
- **One box, no redundancy.** A VM failure takes the API down until it restarts; see
  `docs/RUNBOOK.md`. The static surface is unaffected, which is most of what a reader needs.
- **The avatar's cost caps are monthly and enforced server-side**, so the ceiling on vendor spend is
  a configuration value rather than a hope.

## What is not measured yet

Sustained concurrent-session capacity, the point at which archive queue waits begin to eat the
deadline, and memory under load. All three belong to phase 45, which is where the load testing is
specified. Writing estimates here now would create numbers that look measured and are not.
