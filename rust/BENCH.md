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
