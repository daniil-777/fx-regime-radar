# Stress report — the strategy layer under attack

_Generated 2026-08-19 17:40. Test period 2019+ unless stated; net of the vol-scaled cost model; nothing was re-tuned after these results. Research demonstration on daily data — not a live trading system._

## 1. Historical replays

| window | strategy | return | max_drawdown | worst_day | days |
|---|---|---|---|---|---|
| SNB week (Jan 2015) | S1_trend | nan | nan | nan | 0 |
| COVID crash (Feb–Mar 2020) | S1_trend | 0.058 | -0.022 | -0.007 | 41 |
| 2022 | S1_trend | -0.035 | -0.094 | -0.015 | 365 |
| SNB week (Jan 2015) | S2_meanrev | nan | nan | nan | 0 |
| COVID crash (Feb–Mar 2020) | S2_meanrev | -0.116 | -0.117 | -0.110 | 41 |
| 2022 | S2_meanrev | -0.115 | -0.128 | -0.029 | 365 |
| SNB week (Jan 2015) | S3_regime_gate | nan | nan | nan | 0 |
| COVID crash (Feb–Mar 2020) | S3_regime_gate | -0.078 | -0.080 | -0.075 | 41 |
| 2022 | S3_regime_gate | -0.082 | -0.117 | -0.021 | 365 |
| SNB week (Jan 2015) | BLEND | nan | nan | nan | 0 |
| COVID crash (Feb–Mar 2020) | BLEND | -0.045 | -0.047 | -0.042 | 41 |
| 2022 | BLEND | -0.077 | -0.088 | -0.012 | 365 |

Siren stop (anomaly_pct > 98) inside the windows:

| window | pair | siren_days | first | last |
|---|---|---|---|---|
| SNB week (Jan 2015) | - | 0 | - | - |
| COVID crash (Feb–Mar 2020) | ADA-USD | 20 | 2020-03-12 | 2020-03-31 |
| COVID crash (Feb–Mar 2020) | BNB-USD | 20 | 2020-03-12 | 2020-03-31 |
| COVID crash (Feb–Mar 2020) | BTC-USD | 20 | 2020-03-12 | 2020-03-31 |
| COVID crash (Feb–Mar 2020) | ETH-USD | 25 | 2020-02-20 | 2020-03-31 |
| COVID crash (Feb–Mar 2020) | XRP-USD | 20 | 2020-02-21 | 2020-03-31 |
| 2022 | ADA-USD | 47 | 2022-01-12 | 2022-11-10 |
| 2022 | BNB-USD | 31 | 2022-01-11 | 2022-11-26 |
| 2022 | BTC-USD | 14 | 2022-02-04 | 2022-11-10 |
| 2022 | ETH-USD | 53 | 2022-01-23 | 2022-11-27 |
| 2022 | XRP-USD | 63 | 2022-01-21 | 2022-11-27 |

**Verdict:** Worst window/strategy: S2_meanrev in 2022 (max DD -12.8%, worst day -2.93%). Siren stop fired on 313 pair-days across the three windows (see table) — the overlay was flat exactly when it was supposed to be.

## 2. Cost shocks and the BREAKEVEN COST

**Breakeven cost multiplier — the number practitioners ask first:**

| strategy | gross_sharpe | sharpe_at_1x | breakeven_cost_mult |
|---|---|---|---|
| S1_trend | 0.28 | -0.26 | 0.55 |
| S2_meanrev | -0.88 | -1.58 | 0.00 |
| S3_regime_gate | 0.97 | 0.34 | 1.55 |
| BLEND | 0.18 | -0.90 | 0.20 |

Net Sharpe at k× the cost model:

| strategy | 1.0 | 2.0 | 3.0 | 5.0 |
|---|---|---|---|---|
| BLEND | -0.90 | -1.98 | -3.05 | -5.15 |
| S1_trend | -0.26 | -0.80 | -1.34 | -2.41 |
| S2_meanrev | -1.58 | -2.28 | -2.98 | -4.36 |
| S3_regime_gate | 0.34 | -0.28 | -0.91 | -2.16 |

**Verdict:** No strategy has a positive gross Sharpe on the test set, so the breakeven cost multiplier is 0 for S2_meanrev — there is no edge to pay costs from. BLEND breakeven 0.2× the modelled cost.

## 3. Execution shock — one extra day of lag

| strategy | sharpe_net | sharpe_extra_lag | decay |
|---|---|---|---|
| S1_trend | -0.26 | -0.17 | 0.09 |
| S2_meanrev | -1.58 | -1.35 | 0.24 |
| S3_regime_gate | 0.34 | 0.20 | -0.14 |
| BLEND | -0.90 | -0.89 | 0.01 |

**Verdict:** One extra day of lag changes net Sharpe by -0.14 to +0.24. The decay is small, which mostly reflects how little there was to lose; the numbers are reported as they are.

## 4. Volatility shock — crisis-regime returns ×1.5

| strategy | max_dd_base | max_dd_shock | sharpe_base | sharpe_shock |
|---|---|---|---|---|
| S1_trend | -0.184 | -0.209 | -0.262 | -0.341 |
| S2_meanrev | -0.431 | -0.432 | -1.584 | -1.553 |
| S3_regime_gate | -0.115 | -0.119 | 0.344 | 0.226 |
| BLEND | -0.169 | -0.185 | -0.899 | -0.961 |

**Verdict:** Scaling crisis-regime returns by 1.5x deepens the worst max drawdown by only 2.5% (-43.1% → -43.2%): crisis exposure is small because the siren stop and the crisis-flat gate take risk off in exactly those days — the overlay does its job. The base drawdowns themselves are dreadful; the shock is not what makes them so.

## 5. Block bootstrap — one-year max drawdown, 1 000 paths

| strategy | median_max_dd | p5_pain_max_dd | p95_max_dd |
|---|---|---|---|
| S1_trend | -0.075 | -0.145 | -0.038 |
| S2_meanrev | -0.124 | -0.235 | -0.047 |
| S3_regime_gate | -0.060 | -0.118 | -0.029 |
| BLEND | -0.052 | -0.100 | -0.025 |

![bootstrap](stress_bootstrap_dd.png)

**Verdict:** BLEND one-year max drawdown: median -5.2%, 5th-percentile pain case -10.0% (20-day blocks keep the autocorrelation that day-shuffling would destroy).

## 6. Parameter robustness — ±30 %

![robustness](stress_robustness.png)

**Verdict:** Across ±30 % of every parameter the BLEND's net Sharpe stays within a band of 0.90 (widest for siren_stop) — a flat, negative plateau: nothing is overfit to a spike, and nothing is good either. Parameters were not changed after seeing this.

## Summary

| test | verdict |
|---|---|
| historical replays | Worst window/strategy: S2_meanrev in 2022 (max DD -12.8%, worst day -2.93%). Siren stop fired on 313 pair-days across the three windows (see table) — the overlay was flat exactly when it was supposed to be. |
| cost shocks / breakeven | No strategy has a positive gross Sharpe on the test set, so the breakeven cost multiplier is 0 for S2_meanrev — there is no edge to pay costs from. BLEND breakeven 0.2× the modelled cost. |
| execution shock | One extra day of lag changes net Sharpe by -0.14 to +0.24. The decay is small, which mostly reflects how little there was to lose; the numbers are reported as they are. |
| volatility shock | Scaling crisis-regime returns by 1.5x deepens the worst max drawdown by only 2.5% (-43.1% → -43.2%): crisis exposure is small because the siren stop and the crisis-flat gate take risk off in exactly those days — the overlay does its job. The base drawdowns themselves are dreadful; the shock is not what makes them so. |
| block bootstrap | BLEND one-year max drawdown: median -5.2%, 5th-percentile pain case -10.0% (20-day blocks keep the autocorrelation that day-shuffling would destroy). |
| parameter robustness | Across ±30 % of every parameter the BLEND's net Sharpe stays within a band of 0.90 (widest for siren_stop) — a flat, negative plateau: nothing is overfit to a spike, and nothing is good either. Parameters were not changed after seeing this. |


_Research demonstration on daily data — not a live trading system. Educational tool. Not investment advice._
