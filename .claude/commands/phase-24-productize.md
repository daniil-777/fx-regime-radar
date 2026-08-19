---
description: Phase 24 — productize the axum service: keys, alerts, docs, metrics, widget (next minor tag)
---

Read CLAUDE.md golden rule 11. EXTEND `rust/fxradar-serve` — the startup
gate, golden selftest, and existing endpoints stay exactly as they are.

## Step 0 — confirmed repo map (sanity-check, then confirm)
Pre-filled: axum service with /api/health, /api/regimes/{pair}, POST
/api/score; tracing + latency counters already present; docker-compose;
rust/BENCH.md; deploy target = your Oracle Cloud VM (public subnet, ports via
the security list). Verify, report drift, WAIT.

## Task
Identity at the door, push to where users live, a menu engineers respect,
and public proof it runs — added around the existing engine.

## Requirements
1. Keys: `X-API-Key` header; sha256 hashes only, stored in sqlite via
   rusqlite; tower middleware → 401 unknown; per-key token-bucket rate
   limit; tiny admin CLI (issue/revoke) with a tier field (free/pro/partner
   — enforcement arrives phase 28, the field now).
2. Alert engine: triggers = regime flip, anomaly_pct > 98, consensus → 3/3.
   Registered webhook URLs per key; JSON payload signed HMAC-SHA256 in a
   header; at-least-once with exponential backoff (≤5 tries) on a tokio
   queue — never inside handlers; idempotent via persisted last-alerted
   state per key+pair: one flip = one alert.
3. Slack incoming-webhook + Telegram sendMessage adapters; template text =
   regime, change risk ± interval, consensus line, next scheduled event.
   Template lint test bans direction words.
4. OpenAPI via utoipa on every public route, Swagger UI at /docs.
5. /metrics in Prometheus format (requests, latency histograms, alerts
   fired, delivery failures) via the metrics + exporter crates, joined to
   the existing tracing.
6. Load test (oha or k6) against /api/score and the new routes; append
   p50/p95/p99 + rps to rust/BENCH.md beside the criterion numbers.
7. widget.js served by the service: fetches /api/regimes/{pair}, renders the
   badge (regime dot + word + siren), accepts ?partner= for attribution.
8. Deploy notes for the Oracle VM: compose or systemd, env-file secrets,
   80/443 in the subnet security list, /api/health as the check.

## Do not
No plaintext keys or secrets anywhere. No model math in handlers. No
blocking third-party calls in handlers. No serving on selftest failure —
the gate is sacred. No direction content in alerts.

## Verify
- Bad key → 401; rate limit demonstrated; signature verified by a 10-line
  client script; dead receiver → retries then graceful give-up, visible in
  /metrics; same regime two days → exactly one alert.
- Swagger renders; BENCH.md updated; service answering on the VM.
- cargo test + clippy clean. CHANGELOG, commit `phase-24: productized api`,
  next minor tag.

## Teach me
Push vs pull; why HMAC lets receivers trust us; why at-least-once forces
idempotency; the golden signals. Quiz: (1) why hash the keys? (2) what
breaks if alerts fire inside the request handler? Critique my answers.
