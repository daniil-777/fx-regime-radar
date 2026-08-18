---
description: Phase 14 — cost-aware backtest engine with the lag law (v2.2.0)
---

Read CLAUDE.md, especially golden rule 12. Prerequisite: phases through 08
(this layer consumes regime, change_risk_5d and anomaly_pct). Independent of
the Rust wall phases — build in either order, keep version tags monotonic.

## Task
Build `src/fxradar/backtest.py`: a small, vectorized, brutally honest
backtest engine. It answers one question: after realistic frictions, does a
position series make or lose money?

## Requirements
1. `run_backtest(positions, prices, features, cost_cfg) -> BacktestResult`.
   Positions are a per-pair daily series in [-1, 1] decided from information
   up to day t. THE LAG LAW: the engine itself shifts positions by one day —
   a signal formed at close t earns returns from t+1. This shift lives inside
   the engine, not in caller code, so it cannot be forgotten.
2. Cost model (your colleague's "sometimes very high" commissions, made
   honest): cost_bps_t = base_bps + vol_mult * vol_20_t, so spreads widen
   exactly when markets are stressed. Defaults base_bps=1.0, vol_mult tuned
   so crisis-regime costs are roughly 3–4x calm costs; both configurable and
   documented. Cost is charged on turnover: |position_t − position_{t−1}|.
3. Outputs: daily frame (date, pair, pos, ret_gross, cost, ret_net) plus
   metrics net AND gross: CAGR, annualized vol, Sharpe, max drawdown,
   annual turnover, cost drag (gross CAGR − net CAGR), hit rate. A
   `metrics_table()` renderer for reports.
4. Tests that make the engine trustworthy:
   - Toy exactness: constant long position → net equals asset return minus
     exactly one entry cost; daily sign-flipping position → hand-computed
     cost bleed matches to the cent.
   - THE FORESIGHT TEST: a cheating signal pos_t = sign(ret_{t+1}) must show
     enormous Sharpe with the lag disabled (test-only flag) and near-zero
     with the lag enforced. This single test proves the engine can't be
     fooled by lookahead.
   - Cost monotonicity: higher vol_mult never increases net returns.
5. Save engine output for later phases as `data/backtests.parquet`
   (date, strategy, pair, pos, ret_gross, ret_net, cost_bps).

## Do not
No strategy logic in this phase — the engine is neutral plumbing. No
intraday pretension: daily bars only, say so in the docstring. No metric
reported gross-only.

## Verify
- `make test` green including the foresight test; run the engine on a dummy
  always-long strategy and show me the metrics table, gross vs net.
- CHANGELOG, commit `phase-14: backtest engine`, tag `v2.2.0`.

## Teach me
Explain: why the lag law is the most common backtest sin, and why costs must
scale with volatility. Two interview questions; critique my answers.
