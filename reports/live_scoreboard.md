# Live scoreboard — forward forecasts scored after maturity

Only rows whose 5-trading-day window has completed are scored; each model version is a
separate segment so a refit can never launder an earlier record. Metrics appear at 20 resolved rows; null means not yet defined, never 0.

Frozen test (2019+, scored once): PR-AUC 0.548 · Brier 0.102 (base rate 0.136) · n = 5922

| model version | family | since | through | forecasts | resolved | Brier ↓ | base-rate Brier | PR-AUC ↑ | precision | recall |
|---|---|---|---|---|---|---|---|---|---|---|
| `hmm=0.4.0|fc=1.1.0|siren=1.2.0` | champion | 2026-08-17 | 2026-08-26 | 24 | 9 | — | — | — | — | — |
| `challenger=1.0.0` | challenger | 2026-08-18 | 2026-08-26 | 21 | 6 | — | — | — | — | — |
