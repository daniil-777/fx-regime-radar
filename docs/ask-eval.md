# Ask router — live evaluation

model `none — rules-only run (no model key configured)` · prompt `ask-route-v1` · git `566974a` · 2026-08-24 17:06 UTC · credits 8

Route accuracy: **30/30** (target ≥ 27) · gate violations: **0** (target 0) · rules-vs-model agreement: not measured (no model key)

| expected \ got | conditions | direction_or_advice | official_fact | out_of_scope |
|---|---|---|---|---|
| conditions | 10 | 0 | 0 | 0 |
| direction_or_advice | 0 | 8 | 0 | 0 |
| official_fact | 0 | 0 | 8 | 0 |
| out_of_scope | 0 | 0 | 0 | 4 |

latency p50/p95 ms — rules 0.03/0.22 · model — (no lane) · official_fact end-to-end 3493/5017

Pre-registered pass: routes PASS · gates PASS · rules p50 PASS · model p50 NOT RUN (no model key) · fact p50 FAIL

_Educational tool. Not investment advice._
