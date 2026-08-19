# HMM validation — are these regimes real, stable and useful?

_Generated 2026-08-19 17:34. Train = dates ≤ 2016-12-31; out-of-sample (OOS) = 2017-01-01 onward — nothing after the train end touched the fit. All regime labels are FILTERED (causal)._

## 1. Regime anatomy (train vs out-of-sample)

Frequency, mean run length, annualised vol of daily returns, mean daily return (bp) and worst drawdown of the return stream *inside* each label. Ordering by vol is by construction (calm < … < crisis); everything else is a genuine test.

**EURUSD**

| period | regime | days | freq_pct | mean_duration_d | ann_vol_pct | mean_ret_bp | worst_dd_pct |
|---|---|---|---|---|---|---|---|
| oos | calm | 1451 | 57.97 | 41.46 | 5.77 | 0.65 | -13.01 |
| oos | trend | 208 | 8.31 | 13.00 | 9.72 | -1.55 | -9.65 |
| oos | chop | 754 | 30.12 | 15.71 | 7.72 | -0.60 | -21.34 |
| oos | crisis | 90 | 3.60 | 22.50 | 12.65 | 8.25 | -3.62 |
| train | calm | 766 | 25.21 | 38.30 | 6.00 | 2.88 | -8.24 |
| train | trend | 710 | 23.37 | 16.90 | 9.82 | -2.30 | -21.41 |
| train | chop | 857 | 28.21 | 17.85 | 8.53 | 0.56 | -14.37 |
| train | crisis | 705 | 23.21 | 32.05 | 15.00 | -4.38 | -28.50 |

**USDJPY**

| period | regime | days | freq_pct | mean_duration_d | ann_vol_pct | mean_ret_bp | worst_dd_pct |
|---|---|---|---|---|---|---|---|
| oos | calm | 1221 | 48.76 | 30.52 | 6.07 | 2.26 | -8.12 |
| oos | trend | 376 | 15.02 | 13.93 | 10.55 | 1.95 | -9.25 |
| oos | chop | 675 | 26.96 | 14.06 | 8.62 | 0.68 | -7.83 |
| oos | crisis | 232 | 9.27 | 16.57 | 14.62 | -3.45 | -14.56 |
| train | calm | 915 | 30.10 | 28.59 | 6.61 | 4.23 | -5.40 |
| train | trend | 709 | 23.32 | 20.26 | 11.80 | -0.72 | -20.36 |
| train | chop | 963 | 31.68 | 19.26 | 8.67 | -2.81 | -33.87 |
| train | crisis | 453 | 14.90 | 13.32 | 17.25 | 0.53 | -25.50 |

**GBPUSD**

| period | regime | days | freq_pct | mean_duration_d | ann_vol_pct | mean_ret_bp | worst_dd_pct |
|---|---|---|---|---|---|---|---|
| oos | calm | 530 | 21.17 | 14.32 | 5.95 | 0.51 | -7.65 |
| oos | trend | 610 | 24.37 | 19.06 | 9.86 | 0.10 | -17.46 |
| oos | chop | 1249 | 49.90 | 19.83 | 7.55 | -0.37 | -19.31 |
| oos | crisis | 114 | 4.55 | 22.80 | 17.95 | 9.70 | -6.83 |
| train | calm | 486 | 15.90 | 23.14 | 5.20 | 0.69 | -4.99 |
| train | trend | 880 | 28.80 | 21.46 | 9.92 | -1.58 | -23.33 |
| train | chop | 1414 | 46.27 | 24.81 | 7.75 | -0.61 | -19.95 |
| train | crisis | 276 | 9.03 | 46.00 | 19.41 | -8.29 | -25.82 |

**USDCAD**

| period | regime | days | freq_pct | mean_duration_d | ann_vol_pct | mean_ret_bp | worst_dd_pct |
|---|---|---|---|---|---|---|---|
| oos | calm | 1540 | 61.50 | 40.53 | 5.34 | 1.94 | -4.93 |
| oos | trend | 172 | 6.87 | 21.50 | 8.94 | -5.48 | -10.31 |
| oos | chop | 744 | 29.71 | 16.17 | 7.30 | -2.90 | -25.54 |
| oos | crisis | 48 | 1.92 | 16.00 | 15.56 | 8.15 | -6.15 |
| train | calm | 973 | 31.80 | 31.39 | 6.13 | 3.27 | -6.88 |
| train | trend | 680 | 22.22 | 21.25 | 10.82 | -6.49 | -38.69 |
| train | chop | 1020 | 33.33 | 20.00 | 7.67 | -0.49 | -21.67 |
| train | crisis | 387 | 12.65 | 35.18 | 16.75 | 7.17 | -16.65 |

**AUDUSD**

| period | regime | days | freq_pct | mean_duration_d | ann_vol_pct | mean_ret_bp | worst_dd_pct |
|---|---|---|---|---|---|---|---|
| oos | calm | 1448 | 57.85 | 38.11 | 7.69 | -0.88 | -23.68 |
| oos | trend | 511 | 20.42 | 15.03 | 10.36 | -0.06 | -18.76 |
| oos | chop | 448 | 17.90 | 12.44 | 11.75 | 0.23 | -13.09 |
| oos | crisis | 96 | 3.84 | 24.00 | 19.86 | 10.74 | -6.33 |
| train | calm | 790 | 29.21 | 41.58 | 7.95 | -1.62 | -21.67 |
| train | trend | 738 | 27.28 | 21.71 | 11.18 | 6.91 | -7.71 |
| train | chop | 789 | 29.17 | 19.24 | 12.35 | -5.27 | -36.11 |
| train | crisis | 388 | 14.34 | 43.11 | 27.40 | -0.52 | -28.38 |

**USDCHF**

| period | regime | days | freq_pct | mean_duration_d | ann_vol_pct | mean_ret_bp | worst_dd_pct |
|---|---|---|---|---|---|---|---|
| oos | calm | 2198 | 87.81 | 169.08 | 6.63 | -0.11 | -16.30 |
| oos | trend | 242 | 9.67 | 15.12 | 9.97 | -5.13 | -18.02 |
| oos | chop | 63 | 2.52 | 15.75 | 15.50 | -12.62 | -12.97 |
| oos | crisis | 0 | 0.00 | nan | nan | nan | nan |
| train | calm | 1618 | 52.93 | 44.94 | 7.86 | 1.04 | -19.11 |
| train | trend | 969 | 31.70 | 23.07 | 10.59 | -3.14 | -37.67 |
| train | chop | 450 | 14.72 | 37.50 | 17.43 | 1.45 | -17.65 |
| train | crisis | 20 | 0.65 | 20.00 | 65.93 | -46.36 | -2.18 |

**NZDUSD**

| period | regime | days | freq_pct | mean_duration_d | ann_vol_pct | mean_ret_bp | worst_dd_pct |
|---|---|---|---|---|---|---|---|
| oos | calm | 1448 | 57.83 | 39.14 | 8.33 | -0.45 | -21.28 |
| oos | trend | 146 | 5.83 | 13.27 | 14.47 | -1.97 | -15.34 |
| oos | chop | 816 | 32.59 | 18.55 | 10.00 | -1.82 | -20.47 |
| oos | crisis | 94 | 3.75 | 18.80 | 18.24 | 8.20 | -5.02 |
| train | calm | 771 | 25.25 | 32.12 | 8.48 | 2.96 | -13.97 |
| train | trend | 730 | 23.90 | 16.98 | 14.06 | 0.04 | -15.02 |
| train | chop | 1084 | 35.49 | 18.69 | 11.28 | -3.01 | -30.23 |
| train | crisis | 469 | 15.36 | 42.64 | 22.56 | 1.63 | -28.77 |

**EURGBP**

| period | regime | days | freq_pct | mean_duration_d | ann_vol_pct | mean_ret_bp | worst_dd_pct |
|---|---|---|---|---|---|---|---|
| oos | calm | 1402 | 56.01 | 53.92 | 4.57 | -0.57 | -15.24 |
| oos | trend | 756 | 30.20 | 17.58 | 7.43 | 1.52 | -13.05 |
| oos | chop | 310 | 12.39 | 15.50 | 9.14 | -0.23 | -8.51 |
| oos | crisis | 35 | 1.40 | 17.50 | 15.13 | -9.95 | -7.94 |
| train | calm | 880 | 28.73 | 44.00 | 4.95 | -0.10 | -7.29 |
| train | trend | 1131 | 36.92 | 26.93 | 7.65 | 0.84 | -15.24 |
| train | chop | 895 | 29.22 | 34.42 | 10.01 | -0.99 | -16.43 |
| train | crisis | 157 | 5.13 | 52.33 | 18.86 | 13.93 | -10.70 |

**EURJPY**

| period | regime | days | freq_pct | mean_duration_d | ann_vol_pct | mean_ret_bp | worst_dd_pct |
|---|---|---|---|---|---|---|---|
| oos | calm | 1283 | 51.22 | 32.90 | 6.01 | 1.15 | -17.67 |
| oos | trend | 227 | 9.06 | 15.13 | 12.05 | 3.55 | -9.80 |
| oos | chop | 991 | 39.56 | 19.06 | 9.35 | 2.16 | -9.63 |
| oos | crisis | 4 | 0.16 | 2.00 | 29.82 | -90.71 | -3.99 |
| train | calm | 690 | 22.65 | 23.00 | 6.21 | 2.53 | -7.63 |
| train | trend | 833 | 27.34 | 24.50 | 14.21 | -6.86 | -44.91 |
| train | chop | 1117 | 36.66 | 18.62 | 9.90 | 2.74 | -12.75 |
| train | crisis | 407 | 13.36 | 37.00 | 23.67 | -0.57 | -29.03 |

**USDSEK**

| period | regime | days | freq_pct | mean_duration_d | ann_vol_pct | mean_ret_bp | worst_dd_pct |
|---|---|---|---|---|---|---|---|
| oos | calm | 1471 | 58.75 | 36.77 | 8.59 | 0.43 | -15.65 |
| oos | trend | 666 | 26.60 | 12.11 | 10.32 | -0.42 | -18.25 |
| oos | chop | 313 | 12.50 | 14.90 | 14.09 | 2.94 | -18.73 |
| oos | crisis | 54 | 2.16 | 10.80 | 18.19 | -14.76 | -10.47 |
| train | calm | 1171 | 38.46 | 31.65 | 8.63 | 2.22 | -16.44 |
| train | trend | 866 | 28.44 | 15.46 | 10.85 | -3.73 | -29.07 |
| train | chop | 603 | 19.80 | 19.45 | 14.47 | 1.53 | -19.01 |
| train | crisis | 405 | 13.30 | 45.00 | 22.94 | 5.57 | -27.43 |

Reading: the vol ordering survives out of sample for every pair (a label is not just an in-sample artefact). Mean returns inside labels are tiny relative to vol — regimes describe *conditions*, not direction. Note USDCHF: its `crisis` state was learnt almost entirely from the January-2015 SNB shock (20 train days, ~65 % annualised vol) and never fires out of sample; USDCHF's 2008–2011 stress carries the `chop` name instead. This is a labelling artefact of the frozen naming rule plus one extreme event, and it is reported rather than patched.

## 2. Seed stability

The seed-42 model is the reference; each cell is the share of days on which a model refit with another seed (same data, same naming rule) gives the same label.

| pair | 1 | 2 | 3 | 4 | 5 | mean |
|---|---|---|---|---|---|---|
| AUDUSD | 0.680 | 0.636 | 0.566 | 0.999 | 0.679 | 0.712 |
| EURGBP | 0.624 | 1.000 | 0.487 | 1.000 | 0.971 | 0.817 |
| EURJPY | 0.496 | 0.444 | 0.789 | 0.437 | 0.405 | 0.514 |
| EURUSD | 0.696 | 1.000 | 0.625 | 0.698 | 0.534 | 0.711 |
| GBPUSD | 0.995 | 0.996 | 0.895 | 0.996 | 0.403 | 0.857 |
| NZDUSD | 0.818 | 0.807 | 0.536 | 0.526 | 0.818 | 0.701 |
| USDCAD | 0.913 | 0.890 | 0.827 | 0.871 | 0.827 | 0.866 |
| USDCHF | 0.985 | 0.905 | 0.649 | 0.588 | 0.905 | 0.807 |
| USDJPY | 0.742 | 0.687 | 0.468 | 0.638 | 0.638 | 0.634 |
| USDSEK | 0.914 | 0.527 | 0.898 | 0.513 | 0.910 | 0.753 |

Interpretation, honestly: agreement ranges from 40% to 100%. Some refits land on the same optimum (≥ 99 % agreement) and others on a different one where the middle two states split the data differently — EURJPY is the least stable (mean 51%, below the 80 % warning threshold). The calm/crisis ends are the stable part; the trend/chop split is the fragile part. EM finds local optima, and a rule that names states by mean vol/momentum inherits that. Practical consequences: (a) treat `trend` vs `chop` as soft; (b) a production refit should use several restarts and keep the best likelihood, and be checked against the previous labelling before it replaces it (phase 06 refit path); (c) `regime_prob`/`hmm_entropy` are more trustworthy than the label itself.

## 3. Baseline: does the HMM add anything to a one-line vol rule?

Naive rule: *stressed* when vol_20 is above its trailing 250-day 80th percentile, else *quiet* (causal). Compared with HMM `crisis` out of sample.

| pair | hmm_crisis_pct | naive_stress_pct | agreement_pct | kappa |
|---|---|---|---|---|
| AUDUSD | 3.84 | 20.66 | 83.10 | 0.26 |
| EURGBP | 1.40 | 19.18 | 82.22 | 0.11 |
| EURJPY | 0.16 | 20.84 | 79.32 | 0.01 |
| EURUSD | 3.60 | 19.10 | 84.10 | 0.25 |
| GBPUSD | 4.55 | 19.54 | 83.98 | 0.28 |
| NZDUSD | 3.75 | 18.93 | 84.42 | 0.27 |
| USDCAD | 1.92 | 18.65 | 83.19 | 0.15 |
| USDCHF | 0.00 | 19.62 | 80.38 | 0.00 |
| USDJPY | 9.27 | 19.81 | 84.42 | 0.39 |
| USDSEK | 2.16 | 19.77 | 82.39 | 0.16 |

Where the two disagree the naive rule is usually earlier by construction (a percentile flips the day vol crosses it) while the HMM waits for the transition to be likely — it trades a few days of lag for far fewer flickers (compare mean durations above). Dated episodes (full history) where both flagged stress within 15 trading days of each other (lead_days > 0 = HMM first); the three largest HMM leads are shown:

**EURUSD** — 20 matched episodes; HMM led in 3, naive led in 8, same day 9.

| hmm_start | naive_start | lead_days |
|---|---|---|
| 2011-09-12 | 2011-10-03 | 15 |
| 2010-09-27 | 2010-10-05 | 6 |
| 2011-05-06 | 2011-05-12 | 4 |

**USDJPY** — 35 matched episodes; HMM led in 10, naive led in 12, same day 13.

| hmm_start | naive_start | lead_days |
|---|---|---|
| 2017-01-18 | 2017-01-27 | 7 |
| 2009-11-26 | 2009-12-04 | 6 |
| 2016-06-17 | 2016-06-27 | 6 |

**GBPUSD** — 9 matched episodes; HMM led in 1, naive led in 6, same day 2.

| hmm_start | naive_start | lead_days |
|---|---|---|
| 2006-05-11 | 2006-05-15 | 2 |
| 2016-10-07 | 2016-10-07 | 0 |
| 2017-01-18 | 2017-01-18 | 0 |

**USDCAD** — 11 matched episodes; HMM led in 1, naive led in 9, same day 1.

| hmm_start | naive_start | lead_days |
|---|---|---|
| 2008-03-19 | 2008-04-02 | 9 |
| 2021-01-01 | 2021-01-01 | 0 |
| 2010-05-07 | 2010-05-06 | -1 |

**AUDUSD** — 11 matched episodes; HMM led in 0, naive led in 8, same day 3.

| hmm_start | naive_start | lead_days |
|---|---|---|
| 2008-09-12 | 2008-09-12 | 0 |
| 2020-06-12 | 2020-06-12 | 0 |
| 2025-04-07 | 2025-04-07 | 0 |

**USDCHF** — 1 matched episodes; HMM led in 0, naive led in 0, same day 1.

| hmm_start | naive_start | lead_days |
|---|---|---|
| 2015-01-16 | 2015-01-16 | 0 |

**NZDUSD** — 13 matched episodes; HMM led in 1, naive led in 7, same day 5.

| hmm_start | naive_start | lead_days |
|---|---|---|
| 2010-05-24 | 2010-06-09 | 12 |
| 2008-01-22 | 2008-01-22 | 0 |
| 2011-07-14 | 2011-07-14 | 0 |

**EURGBP** — 3 matched episodes; HMM led in 0, naive led in 3, same day 0.

| hmm_start | naive_start | lead_days |
|---|---|---|
| 2020-03-19 | 2020-03-17 | -2 |
| 2022-10-05 | 2022-09-26 | -7 |
| 2016-06-13 | 2016-05-25 | -13 |

**EURJPY** — 10 matched episodes; HMM led in 1, naive led in 5, same day 4.

| hmm_start | naive_start | lead_days |
|---|---|---|
| 2012-02-27 | 2012-03-07 | 7 |
| 2008-08-26 | 2008-08-26 | 0 |
| 2013-01-11 | 2013-01-11 | 0 |

**USDSEK** — 11 matched episodes; HMM led in 2, naive led in 6, same day 3.

| hmm_start | naive_start | lead_days |
|---|---|---|
| 2022-04-01 | 2022-04-22 | 15 |
| 2010-05-07 | 2010-05-10 | 1 |
| 2008-08-26 | 2008-08-26 | 0 |

Verdict: the HMM does **not** systematically lead the naive rule — across all matched episodes it led in 19 and lagged in 64. When it leads it can be by several days (EURUSD, autumn 2011), but more often it is simultaneous or later. Its value is not earlier warnings but a four-way, sticky, probabilistic description (with confidence and entropy) instead of a binary flicker — and that is what the forecaster and narrator consume.

## 4. Economic meaning: a toy trend rule inside each regime (out of sample)

MA(50/200) long/short decided at t, earned at t+1, gross of costs — a diagnostic only. Claim under test: trend-following should look best in `trend` and worst in `chop`.

**EURUSD**

| regime | days | sharpe | ann_ret_pct |
|---|---|---|---|
| calm | 1450 | -0.27 | -1.70 |
| trend | 208 | -0.22 | -1.98 |
| chop | 754 | 0.77 | 5.88 |
| crisis | 90 | -2.41 | -25.64 |
| ALL | 2502 | -0.04 | -0.30 |

**USDJPY**

| regime | days | sharpe | ann_ret_pct |
|---|---|---|---|
| calm | 1221 | -0.17 | -1.18 |
| trend | 376 | 0.55 | 5.48 |
| chop | 674 | -0.24 | -2.05 |
| crisis | 232 | -1.36 | -18.47 |
| ALL | 2503 | -0.23 | -2.01 |

**GBPUSD**

| regime | days | sharpe | ann_ret_pct |
|---|---|---|---|
| calm | 529 | -0.42 | -3.06 |
| trend | 610 | -0.05 | -0.49 |
| chop | 1249 | -0.20 | -1.52 |
| crisis | 114 | -1.37 | -20.30 |
| ALL | 2502 | -0.28 | -2.45 |

**USDCAD**

| regime | days | sharpe | ann_ret_pct |
|---|---|---|---|
| calm | 1539 | -0.28 | -1.68 |
| trend | 172 | -1.17 | -9.46 |
| chop | 744 | 0.08 | 0.58 |
| crisis | 48 | -1.26 | -16.03 |
| ALL | 2503 | -0.28 | -1.82 |

**AUDUSD**

| regime | days | sharpe | ann_ret_pct |
|---|---|---|---|
| calm | 1447 | 0.66 | 5.58 |
| trend | 511 | -0.90 | -9.17 |
| chop | 448 | -0.40 | -4.34 |
| crisis | 96 | -2.57 | -42.93 |
| ALL | 2502 | -0.11 | -1.07 |

**USDCHF**

| regime | days | sharpe | ann_ret_pct |
|---|---|---|---|
| calm | 2197 | -0.57 | -3.89 |
| trend | 242 | -0.90 | -9.35 |
| chop | 63 | 0.06 | 0.59 |
| crisis | 0 | nan | nan |
| ALL | 2502 | -0.58 | -4.30 |

**NZDUSD**

| regime | days | sharpe | ann_ret_pct |
|---|---|---|---|
| calm | 1447 | -0.48 | -4.27 |
| trend | 146 | -0.30 | -4.30 |
| chop | 816 | -0.56 | -5.38 |
| crisis | 94 | -3.07 | -46.31 |
| ALL | 2503 | -0.63 | -6.21 |

**EURGBP**

| regime | days | sharpe | ann_ret_pct |
|---|---|---|---|
| calm | 1401 | 0.22 | 1.10 |
| trend | 756 | -0.10 | -0.80 |
| chop | 310 | -2.41 | -19.21 |
| crisis | 35 | 5.09 | 55.79 |
| ALL | 2502 | -0.19 | -1.23 |

**EURJPY**

| regime | days | sharpe | ann_ret_pct |
|---|---|---|---|
| calm | 1283 | 0.84 | 5.75 |
| trend | 227 | -0.89 | -9.10 |
| chop | 990 | -0.08 | -0.75 |
| crisis | 4 | -3.32 | -15.09 |
| ALL | 2504 | 0.22 | 1.80 |

**USDSEK**

| regime | days | sharpe | ann_ret_pct |
|---|---|---|---|
| calm | 1470 | -0.02 | -0.22 |
| trend | 666 | -0.33 | -3.41 |
| chop | 313 | 0.55 | 7.24 |
| crisis | 54 | -0.22 | -3.38 |
| ALL | 2503 | -0.02 | -0.21 |

Reading: EURUSD: best in `chop`, worst in `crisis`; USDJPY: best in `trend`, worst in `crisis`; GBPUSD: best in `trend`, worst in `crisis`; USDCAD: best in `chop`, worst in `crisis`; AUDUSD: best in `calm`, worst in `crisis`; USDCHF: best in `chop`, worst in `trend`; NZDUSD: best in `trend`, worst in `crisis`; EURGBP: best in `crisis`, worst in `chop`; EURJPY: best in `calm`, worst in `crisis`; USDSEK: best in `chop`, worst in `trend`. The claim holds for 3/3 pairs on 'best in trend' and 1/3 on 'worst in chop' — it does **not** hold as a general pattern, and `crisis` is where a moving-average rule gets whipsawed hardest. Differences between labels are also within noise for these sample sizes. The regimes are descriptive states of volatility/momentum, not a trading edge, and this report says so.

## 5. Plots

![EURUSD timeline](regimes_timeline_EURUSD.png)

![USDJPY timeline](regimes_timeline_USDJPY.png)

![GBPUSD timeline](regimes_timeline_GBPUSD.png)

![USDCAD timeline](regimes_timeline_USDCAD.png)

![AUDUSD timeline](regimes_timeline_AUDUSD.png)

![USDCHF timeline](regimes_timeline_USDCHF.png)

![NZDUSD timeline](regimes_timeline_NZDUSD.png)

![EURGBP timeline](regimes_timeline_EURGBP.png)

![EURJPY timeline](regimes_timeline_EURJPY.png)

![USDSEK timeline](regimes_timeline_USDSEK.png)

![durations](regime_durations.png)

## 6. Limitations

- **Daily data only.** Intraday storms are averaged away; Yahoo's daily close is a start-of-day snapshot, so returns are one day late relative to highs/lows.
- **Label noise.** Filtered labels flicker near state boundaries and the trend/chop split is seed-sensitive (section 2). Read `regime_prob` and `hmm_entropy` with the label.
- **Descriptive, not predictive.** A regime describes the recent past; the transition matrix says regimes are sticky, nothing more. Direction is not modelled anywhere.
- **Frozen naming rule + rare events.** One extreme episode (SNB 2015) can own a whole state (USDCHF); the rule then mislabels the ordinary stress state.
- **Single training window (2005–2016).** Post-2016 structure (2020, 2022) is scored, not learnt; a monthly expanding refit is the phase-06 plan.
- **Gaussian emissions.** Fat tails are absorbed by the high-vol state rather than modelled.


_Educational tool. Not investment advice._
