---
description: Phase 13 — Axum production service with refuse-to-start gate (v2.1.0)
---

Read CLAUDE.md golden rule 11. This phase turns the engine into the
production layer: an HTTP service that would rather die than serve numbers
that disagree with research.

## Task
Extend `rust/fxradar-serve` with an Axum HTTP service, containerize it, and
wire the dashboard to consume it.

## Requirements
1. Startup sequence, in order: load bundle → verify manifest hashes → run the
   full golden-vector self-test in-process → only then bind the port. On any
   failure: log the diff table with `tracing` and exit nonzero. Add a
   `--skip-selftest` flag that exists but logs a loud warning (for dev only).
2. Endpoints:
   - `GET /api/health`: bundle version, git commit, selftest status and
     timestamp, uptime.
   - `GET /api/regimes/{pair}`: latest scored state for the pair (reads the
     current artifacts/state store).
   - `POST /api/score`: accepts a raw recent-price window per pair, runs the
     full Rust path, returns the ScoredRow — the live, on-demand proof.
   - JSON errors with proper status codes; request logging with latency via
     `tracing`; simple in-memory p50/p99 latency counters exposed on /health.
3. Docker: multi-stage build (rust builder → slim runtime); add the service
   to a `docker-compose.yml` alongside the existing app; document ports.
4. Dashboard integration: the Streamlit app gets a `FXRADAR_API_URL` env
   switch — when set, weather cards read from `GET /api/regimes/*` instead of
   parquet, with a small "served by rust vX" badge next to the timestamp.
   Default behavior unchanged.
5. Load check: a scripted 1,000-request run against `POST /api/score`;
   record p50/p99 in `rust/BENCH.md` next to the criterion numbers.
6. README: new "Production serving" section with the wall architecture in
   mermaid, the startup-gate story, and the measured latencies.

## Do not
No model math in handlers (handlers call the engine). No serving on selftest
failure. No secrets; the service needs none. The LLM narration stays on the
Python side — the service serves its output, never calls the API itself.

## Verify
- `docker compose up`; curl all three endpoints and show me the outputs.
- Corrupt one golden value in a scratch copy of the bundle and demonstrate
  the service refusing to start, with its log line.
- Show p50/p99. CHANGELOG, commit `phase-13: axum service`, tag `v2.1.0`.

## Teach me
Explain: why refuse-to-start beats serve-and-hope, and why p99 matters more
than average latency in trading systems. Two interview questions; critique
my answers, then quiz me once on the whole wall architecture end to end.
