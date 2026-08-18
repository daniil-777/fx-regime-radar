# Strategy evaluation — S1 trend, S2 mean reversion, S3 regime gate, BLEND

_Generated 2026-08-18 13:10. Daily bars, three pairs equal weight, costs 8 bp + 20×vol_20 on turnover, lag law inside the engine, overlay on every strategy (risk scaling above 0.3, siren stop above 98.0, 10% vol target, 2× cap). Parameters fixed on train+val; **test 2019+ scored once and frozen.** Research demonstration on daily data — not a live trading system._

## train — gross vs net (all pairs equal weight)

| strategy | kind | cagr | ann_vol | sharpe | max_drawdown | turnover_ann | cost_drag | hit_rate |
|---|---|---|---|---|---|---|---|---|
| S1_trend | gross | 0.172 | 0.120 | 1.387 | -0.156 | 24.619 | 0.000 | 0.518 |
| S1_trend | net | 0.113 | 0.121 | 0.947 | -0.189 | 24.619 | 0.059 | 0.484 |
| S2_meanrev | gross | -0.136 | 0.123 | -1.130 | -0.604 | 33.962 | 0.000 | 0.459 |
| S2_meanrev | net | -0.193 | 0.123 | -1.679 | -0.737 | 33.962 | 0.057 | 0.403 |
| S3_regime_gate | gross | 0.158 | 0.111 | 1.382 | -0.105 | 27.648 | 0.000 | 0.503 |
| S3_regime_gate | net | 0.096 | 0.111 | 0.882 | -0.142 | 27.648 | 0.062 | 0.457 |
| BLEND | gross | 0.067 | 0.065 | 1.027 | -0.076 | 28.944 | 0.000 | 0.522 |
| BLEND | net | 0.006 | 0.066 | 0.126 | -0.142 | 28.944 | 0.061 | 0.446 |

## val — gross vs net (all pairs equal weight)

| strategy | kind | cagr | ann_vol | sharpe | max_drawdown | turnover_ann | cost_drag | hit_rate |
|---|---|---|---|---|---|---|---|---|
| S1_trend | gross | 0.038 | 0.105 | 0.406 | -0.121 | 24.009 | 0.000 | 0.455 |
| S1_trend | net | -0.021 | 0.104 | -0.156 | -0.134 | 24.009 | 0.059 | 0.432 |
| S2_meanrev | gross | -0.138 | 0.126 | -1.106 | -0.293 | 29.475 | 0.000 | 0.480 |
| S2_meanrev | net | -0.195 | 0.127 | -1.643 | -0.369 | 29.475 | 0.057 | 0.413 |
| S3_regime_gate | gross | -0.057 | 0.113 | -0.462 | -0.204 | 28.415 | 0.000 | 0.470 |
| S3_regime_gate | net | -0.116 | 0.113 | -1.034 | -0.255 | 28.415 | 0.059 | 0.420 |
| BLEND | gross | -0.060 | 0.076 | -0.773 | -0.147 | 27.096 | 0.000 | 0.474 |
| BLEND | net | -0.118 | 0.076 | -1.604 | -0.239 | 27.096 | 0.058 | 0.426 |

## test — gross vs net (all pairs equal weight)

| strategy | kind | cagr | ann_vol | sharpe | max_drawdown | turnover_ann | cost_drag | hit_rate |
|---|---|---|---|---|---|---|---|---|
| S1_trend | gross | -0.005 | 0.083 | -0.021 | -0.180 | 29.126 | 0.000 | 0.477 |
| S1_trend | net | -0.057 | 0.083 | -0.660 | -0.296 | 29.126 | 0.052 | 0.435 |
| S2_meanrev | gross | -0.050 | 0.102 | -0.451 | -0.232 | 39.257 | 0.000 | 0.512 |
| S2_meanrev | net | -0.114 | 0.102 | -1.138 | -0.365 | 39.257 | 0.064 | 0.457 |
| S3_regime_gate | gross | 0.063 | 0.085 | 0.759 | -0.105 | 31.814 | 0.000 | 0.482 |
| S3_regime_gate | net | 0.002 | 0.085 | 0.069 | -0.132 | 31.814 | 0.060 | 0.439 |
| BLEND | gross | 0.007 | 0.052 | 0.166 | -0.077 | 33.100 | 0.000 | 0.480 |
| BLEND | net | -0.051 | 0.052 | -0.981 | -0.203 | 33.100 | 0.059 | 0.405 |

## Per-regime attribution — test, net Sharpe by the regime known when the position was decided

| strategy | calm | trend | chop | crisis |
|---|---|---|---|---|
| BLEND | -0.86 | 0.55 | -1.38 | -1.48 |
| S1_trend | -0.32 | 0.85 | -1.82 | -2.67 |
| S2_meanrev | -1.21 | -1.53 | -0.16 | 2.42 |
| S3_regime_gate | -0.05 | 1.07 | -0.30 | -3.76 |

Claim under test: trend earns in `trend` and bleeds in `chop`. Measured (S1, test): trend 0.85, chop -1.82, calm -0.32, crisis -2.67 → the pattern holds in sign. Sample sizes per regime are small out of sample (see days), so treat these as directional, not significant.

## Vol targeting and the leverage cap

Target 10% per pair with a hard 2× cap. Because the base signals average only ~0.4 in size, the cap binds on roughly half to four-fifths of training days and realised vol lands at 6–9 % per pair (pooled across three pairs it is lower still). Raising the cap would be a tuning decision we do not take; the target is therefore a ceiling-aware target, and the strategies never run hotter than it.

## Correlation of net daily returns — test

|  | S1_trend | S2_meanrev | S3_regime_gate |
|---|---|---|---|
| S1_trend | 1.000 | -0.518 | 0.506 |
| S2_meanrev | -0.518 | 1.000 | 0.052 |
| S3_regime_gate | 0.506 | 0.052 | 1.000 |

## The mutual-insurance claim

Blend max drawdown (test, net) -20.3% vs best single strategy S3_regime_gate -13.2% → **the blend does NOT beat the best single strategy on drawdown** in this sample — the insurance claim fails here. Blend Sharpe -0.98 vs S1_trend -0.66, S2_meanrev -1.14, S3_regime_gate 0.07.

![equity](strategy_equity.png)

## Honest closing paragraph

Out of sample and net of costs, 1 of the four series have a positive Sharpe and 3 do not (S1_trend, S2_meanrev, BLEND). Cost drag on the test set runs from 5.2% to 6.4% of CAGR per year — the vol-scaled cost model bites exactly where the strategies trade most. This is the expected outcome, stated in advance: on daily FX bars, with honest lags and honest costs, mechanical rules plus a regime gate do not produce a reliable edge. What the exercise delivers is the framework — a lag-law engine, a stress-aware cost model, an overlay that provably de-risks on the siren and change-risk signals, and a blend whose diversification benefit is measured rather than assumed — and the honesty to report the numbers as they are.


_Research demonstration on daily data — not a live trading system. Educational tool. Not investment advice._
