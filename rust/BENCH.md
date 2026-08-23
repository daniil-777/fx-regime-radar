# Rust engine benchmarks

Machine: Apple Silicon (arm64) laptop, `cargo bench --bench scoring`, release profile (thin LTO),
onnxruntime 1.28 CPU provider, single thread. Bundle v1.4.0, 302 golden vectors.

| benchmark | result |
|---|---|
| `score_single_row_full_path` — one pair, raw 600-day windows for all three pairs → features → HMM forward filter (540 steps) → forecaster.onnx → siren.onnx | **≈ 0.43 ms** per call (mean 426 µs, median 423 µs) |
| `throughput/score_10k_rows` — 10 000 full-path calls | **4.4 s** ≈ **2 260 rows/s** |
| `selftest` (302 goldens end-to-end, incl. parquet read + hash verification) | ≈ 0.4 s |

Honest interpretation: the ONNX calls are microseconds; almost all of the 0.43 ms is recomputing
600 rows of features (including three pairwise rolling correlations) and the 540-step forward
filter from scratch on every call. That is the price of a stateless, self-contained scoring path
that reproduces Python bit-for-bit from raw prices; a streaming server that carried the previous
day's filtered probabilities and rolling sums would be one to two orders of magnitude faster, at
the cost of state to keep correct. For a daily product with three pairs, 0.43 ms is irrelevant.

## Service (phase 13) — `POST /api/score`, 1 000 sequential requests

`tools/load_check.py http://127.0.0.1:8080 1000` (real 600-day windows for all three pairs per
request, ~55 KB JSON each; laptop, localhost):

| measure | result |
|---|---|
| server-side scoring latency (engine only, from `/api/health` counters) | **p50 0.42 ms · p99 0.48 ms** |
| client-observed round trip (JSON parse + engine + serialise, Python `urllib`) | p50 0.99 ms · p99 1.46 ms · max 3.9 ms |
| sequential throughput | ≈ 980 req/s |

Start-up gate on bundle v1.4.0: hash verification + 302-golden self-test ≈ 0.5 s before the port
is bound. p99 is what matters: a trading system lives on its worst common case, not its average.

## Phase 24 — productised service (keys, alerts, docs, metrics, widget)

`tools/load_test.py http://127.0.0.1:8099 <pro-key> --n 4000 --c 8` — 8 keep-alive Python
clients, laptop (Apple M3 Pro, arm64), localhost, release build, service started with
`--rate-limit-per-min 1000000` (the 60/min default is a product quota, not a throughput limit).
Client-observed round trip, Python `http.client` overhead included:

| route | concurrency | throughput | p50 | p95 | p99 | max |
|---|---|---|---|---|---|---|
| `GET /api/regimes/EURUSD` (public, mtime-cached newest rows) | 8 | **≈ 9 600 req/s** | 0.38 ms | 1.18 ms | 1.74 ms | 178 ms (first hit = parquet scan → cache fill) |
| `GET /api/health` | 8 | ≈ 15 900 req/s | 0.39 ms | 1.23 ms | 1.83 ms | 6.5 ms |
| `POST /api/score` (X-API-Key, pro tier; real 600-day windows, ~55 KB JSON) | 8 | **≈ 2 180 req/s** | 3.55 ms | 4.14 ms | 4.41 ms | 7.3 ms |
| `POST /api/score` | 1 | ≈ 1 220 req/s | 0.77 ms | 1.06 ms | 1.37 ms | 11 ms |

Honest reading: the engine is single-threaded behind a mutex (one ONNX session pair), so with
8 clients `/api/score` latency is mostly queueing (≈ 8 × 0.45 ms); throughput is the engine's
≈ 2 200 rows/s from the criterion bench, now with key lookup (sqlite, in-process), rate-limit
bookkeeping and the Prometheus middleware in the path — they cost nothing measurable. Before this
phase `/api/regimes/{pair}` re-scanned the whole `regimes.parquet` per request (≈ 180 ms p50 at
c=8, 43 req/s); the newest-row map is now cached on (mtime, size) and re-read only when the
pipeline rewrites the file. `oha`/`k6` were not installed on this machine, hence the Python client;
numbers are upper bounds on latency (client overhead is inside them), not lower bounds.


## Concurrency, phase 45

**Measured on `macOS-26.5.1-arm64-arm-64bit` (arm) — NOT on the
Oracle VM.** The VM is a CPU-only ARM instance; these absolute numbers do not transfer to it and are
not presented as capacity figures for it. `docs/CAPACITY.md` records which figures are still owed.

What does transfer is the shape: whether latency degrades smoothly or falls off a cliff, whether
errors appear before saturation, and how resident memory grows per concurrent session.

Each level ran for a fixed wall-clock window with N threads issuing back-to-back requests, so the
request counts differ by level and throughput is the comparable number.

### Archive path (the slow lane)

| concurrent sessions | requests | req/s | p50 ms | p95 ms | p99 ms | max ms | errors | RSS MB |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 331 | 110.3 | 8.8 | 9.8 | 15.0 | 38.5 | 0 | 28.1 |
| 3 | 880 | 293.3 | 10.2 | 11.0 | 17.2 | 18.2 | 0 | 32.6 |
| 5 | 1402 | 467.3 | 10.4 | 13.2 | 18.2 | 20.3 | 0 | 36.6 |
| 10 | 2348 | 782.7 | 12.2 | 16.8 | 20.9 | 32.0 | 0 | 44.3 |

### Pack path (the common path), for contrast

| concurrent sessions | requests | req/s | p50 ms | p95 ms | p99 ms | max ms | errors | RSS MB |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 359 | 119.7 | 8.3 | 8.8 | 9.4 | 10.8 | 0 | 45.3 |
| 5 | 1458 | 486.0 | 9.9 | 15.2 | 17.7 | 19.2 | 0 | 46.5 |
| 10 | 2476 | 825.3 | 11.5 | 15.9 | 21.6 | 38.0 | 0 | 47.8 |

Resident memory: **19.8 MB at rest, 47.8 MB peak** across every level. The service loads its
indices, packs and archive once at start-up and holds them read-only, so memory is a function of the
artifacts rather than of concurrency — which is why the figure barely moves between 1 and 10 sessions
and why **memory, not CPU, is the binding constraint on a small box**: the floor is paid before the
first request arrives.

### Errors

Zero at every level. Saturation on this host was never reached, so **the concurrency limit cannot be
set from this run** — a limit derived from a machine that never struggled would be a guess wearing a
number. It has to come from the VM.

_Educational tool. Not investment advice._
