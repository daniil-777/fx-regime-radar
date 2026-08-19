# Challenger evaluation — champion vs challenger (phase 23)

_Generated 2026-08-19 16:12. Same labels, splits (train <= 2016-12-31, val 2017–2018, test 2019+), 5-day embargo, XGB params, Platt calibration on val and threshold rule (recall >= 60% on val) as the champion. The only change is the matrix: 15 champion features + 31 extended (calendar countdowns, lagged cross-asset / EPU / COT, Yang-Zhang). The test set was scored ONCE for this report and is frozen._

## Scoreboard (never accuracy)

| model | split | threshold | pr_auc | precision | recall | brier | n | pos_rate |
|---|---|---|---|---|---|---|---|---|
| champion v1.1.0 | val | 0.220 | 0.481 | 0.390 | 0.618 | 0.119 | 1527 | 0.180 |
| challenger v1.0.0 | val | 0.220 | 0.462 | 0.386 | 0.622 | 0.121 | 1527 | 0.180 |
| base_rate | val | 0.500 | 0.180 | 0.000 | 0.000 | 0.148 | 1527 | 0.180 |
| champion v1.1.0 | test | 0.220 | 0.548 | 0.452 | 0.593 | 0.102 | 5925 | 0.162 |
| challenger v1.0.0 | test | 0.220 | 0.544 | 0.421 | 0.602 | 0.103 | 5925 | 0.162 |
| base_rate | test | 0.500 | 0.162 | 0.000 | 0.000 | 0.136 | 5925 | 0.162 |

Train rows 9136, val rows 1527; early stopping at iteration 116 (val PR-AUC 0.460); threshold 0.22.

## Where the extended features rank (XGBoost gain, top 15)

| feature | gain |
|---|---|
| hmm_entropy | 0.121 |
| vol_trend | 0.050 |
| vol_60 | 0.036 |
| vol_ratio | 0.035 |
| pair_USDCHF | 0.032 |
| cot_eur_net | 0.031 |
| rng_hl | 0.030 |
| vol_20 | 0.030 |
| days_in_regime | 0.029 |
| cot_eur_net_z52 | 0.027 |
| days_since_SNB | 0.027 |
| regime_trend | 0.025 |
| vol_20_yz | 0.024 |
| corr_20 | 0.023 |
| regime_chop | 0.023 |

4 of the top-15 gain features come from features_ext.

## Honest reading

On the frozen test set the challenger's PR-AUC is 0.544 vs the champion's 0.548 (-0.004); Brier 0.1031 vs 0.1024 (+0.0008, lower is better). That is within the noise of one test window — conditioning on the calendar and context does not obviously beat the frozen champion here, which is itself a finding: scheduled-event countdowns move volatility, not necessarily the HMM's regime label. Either way the decision is not taken here: the two models now race on the live ledger.

## Promotion criteria

Promote only if the challenger's live PR-AUC on the ledger (matured rows, same outcomes as the champion) exceeds the champion's over >= 60 matured days AND its Brier score is not worse; promotion is a deliberate refit-path act (re-export, new model_version, CHANGELOG), never automatic. The frozen test scoreboard below is context, not the promotion trigger.


_Educational tool. Not investment advice._
