# HMM validation — are these regimes real, stable and useful?

_Generated 2026-08-19 17:51. Train = dates ≤ 2016-12-31; out-of-sample (OOS) = 2017-01-01 onward — nothing after the train end touched the fit. All regime labels are FILTERED (causal)._

## 1. Regime anatomy (train vs out-of-sample)

Frequency, mean run length, annualised vol of daily returns, mean daily return (bp) and worst drawdown of the return stream *inside* each label. Ordering by vol is by construction (calm < … < crisis); everything else is a genuine test.

**USDMXN**

| period | regime | days | freq_pct | mean_duration_d | ann_vol_pct | mean_ret_bp | worst_dd_pct |
|---|---|---|---|---|---|---|---|
| oos | calm | 548 | 21.87 | 26.10 | 6.56 | -3.77 | -20.84 |
| oos | trend | 888 | 35.43 | 20.18 | 12.39 | -1.45 | -27.65 |
| oos | chop | 769 | 30.69 | 13.98 | 9.79 | 1.13 | -13.82 |
| oos | crisis | 301 | 12.01 | 21.50 | 20.98 | 1.77 | -15.25 |
| train | calm | 858 | 28.00 | 34.32 | 6.34 | -2.63 | -25.48 |
| train | trend | 810 | 26.44 | 23.14 | 13.00 | 1.83 | -13.90 |
| train | chop | 1069 | 34.89 | 20.96 | 9.09 | 4.93 | -13.96 |
| train | crisis | 327 | 10.67 | 36.33 | 26.59 | 4.89 | -20.38 |

**USDBRL**

| period | regime | days | freq_pct | mean_duration_d | ann_vol_pct | mean_ret_bp | worst_dd_pct |
|---|---|---|---|---|---|---|---|
| oos | calm | 993 | 39.67 | 26.13 | 10.62 | 1.97 | -16.17 |
| oos | trend | 303 | 12.11 | 12.62 | 18.47 | -5.24 | -19.72 |
| oos | chop | 1129 | 45.11 | 19.81 | 16.74 | 3.33 | -17.12 |
| oos | crisis | 78 | 3.12 | 7.80 | 32.24 | 7.23 | -11.13 |
| train | calm | 1028 | 37.84 | 44.70 | 9.91 | -0.91 | -28.72 |
| train | trend | 556 | 20.46 | 25.27 | 21.32 | -6.58 | -33.50 |
| train | chop | 924 | 34.01 | 23.69 | 17.23 | 9.17 | -16.79 |
| train | crisis | 209 | 7.69 | 13.93 | 43.43 | -0.67 | -37.55 |

**USDZAR**

| period | regime | days | freq_pct | mean_duration_d | ann_vol_pct | mean_ret_bp | worst_dd_pct |
|---|---|---|---|---|---|---|---|
| oos | calm | 748 | 29.91 | 22.00 | 10.44 | -1.98 | -28.51 |
| oos | trend | 637 | 25.47 | 16.76 | 17.03 | 0.05 | -17.39 |
| oos | chop | 1080 | 43.18 | 15.65 | 14.46 | 2.00 | -15.82 |
| oos | crisis | 36 | 1.44 | 18.00 | 27.08 | 29.80 | -6.35 |
| train | calm | 830 | 27.14 | 27.67 | 10.53 | -0.72 | -36.21 |
| train | trend | 1115 | 36.46 | 27.20 | 18.89 | 3.89 | -18.82 |
| train | chop | 915 | 29.92 | 15.25 | 14.13 | 4.21 | -20.81 |
| train | crisis | 198 | 6.47 | 22.00 | 37.46 | 1.32 | -27.43 |

**USDPLN**

| period | regime | days | freq_pct | mean_duration_d | ann_vol_pct | mean_ret_bp | worst_dd_pct |
|---|---|---|---|---|---|---|---|
| oos | calm | 1354 | 54.07 | 46.69 | 7.77 | -0.09 | -19.90 |
| oos | trend | 946 | 37.78 | 24.26 | 11.02 | -1.04 | -28.33 |
| oos | chop | 161 | 6.43 | 13.42 | 15.16 | 2.75 | -11.92 |
| oos | crisis | 43 | 1.72 | 21.50 | 22.04 | -11.22 | -9.30 |
| train | calm | 723 | 23.75 | 28.92 | 8.15 | -2.46 | -27.10 |
| train | trend | 992 | 32.59 | 22.04 | 11.57 | 2.33 | -16.86 |
| train | chop | 899 | 29.53 | 35.96 | 15.67 | -5.92 | -45.29 |
| train | crisis | 430 | 14.13 | 61.43 | 29.02 | 17.38 | -27.46 |

**USDRUB**

| period | regime | days | freq_pct | mean_duration_d | ann_vol_pct | mean_ret_bp | worst_dd_pct |
|---|---|---|---|---|---|---|---|
| oos | calm | 202 | 8.08 | 12.62 | 6.35 | -6.18 | -12.39 |
| oos | trend | 1017 | 40.68 | 22.11 | 16.36 | 4.08 | -18.63 |
| oos | chop | 780 | 31.20 | 17.73 | 9.91 | 1.31 | -8.04 |
| oos | crisis | 501 | 20.04 | 27.83 | 52.18 | -0.99 | -62.25 |
| train | calm | 896 | 30.42 | 44.80 | 4.75 | -2.03 | -21.36 |
| train | trend | 752 | 25.53 | 25.93 | 15.59 | 3.83 | -14.87 |
| train | chop | 938 | 31.85 | 26.06 | 9.49 | 1.82 | -19.14 |
| train | crisis | 359 | 12.19 | 29.92 | 37.15 | 13.85 | -25.02 |

Reading: the vol ordering survives out of sample for every pair (a label is not just an in-sample artefact). Mean returns inside labels are tiny relative to vol — regimes describe *conditions*, not direction. Note USDCHF: its `crisis` state was learnt almost entirely from the January-2015 SNB shock (20 train days, ~65 % annualised vol) and never fires out of sample; USDCHF's 2008–2011 stress carries the `chop` name instead. This is a labelling artefact of the frozen naming rule plus one extreme event, and it is reported rather than patched.

## 2. Seed stability

The seed-42 model is the reference; each cell is the share of days on which a model refit with another seed (same data, same naming rule) gives the same label.

| pair | 1 | 2 | 3 | 4 | 5 | mean |
|---|---|---|---|---|---|---|
| USDBRL | 0.571 | 1.000 | 0.776 | 0.981 | 0.981 | 0.862 |
| USDMXN | 0.906 | 1.000 | 1.000 | 1.000 | 0.918 | 0.965 |
| USDPLN | 0.397 | 0.876 | 0.422 | 0.874 | 0.532 | 0.620 |
| USDRUB | 0.962 | 1.000 | 0.703 | 1.000 | 0.951 | 0.923 |
| USDZAR | 0.429 | 1.000 | 0.427 | 0.668 | 0.500 | 0.605 |

Interpretation, honestly: agreement ranges from 40% to 100%. Some refits land on the same optimum (≥ 99 % agreement) and others on a different one where the middle two states split the data differently — USDZAR is the least stable (mean 60%, below the 80 % warning threshold). The calm/crisis ends are the stable part; the trend/chop split is the fragile part. EM finds local optima, and a rule that names states by mean vol/momentum inherits that. Practical consequences: (a) treat `trend` vs `chop` as soft; (b) a production refit should use several restarts and keep the best likelihood, and be checked against the previous labelling before it replaces it (phase 06 refit path); (c) `regime_prob`/`hmm_entropy` are more trustworthy than the label itself.

## 3. Baseline: does the HMM add anything to a one-line vol rule?

Naive rule: *stressed* when vol_20 is above its trailing 250-day 80th percentile, else *quiet* (causal). Compared with HMM `crisis` out of sample.

| pair | hmm_crisis_pct | naive_stress_pct | agreement_pct | kappa |
|---|---|---|---|---|
| USDBRL | 3.12 | 20.18 | 82.94 | 0.23 |
| USDMXN | 12.01 | 18.44 | 84.72 | 0.41 |
| USDPLN | 1.72 | 21.25 | 80.47 | 0.12 |
| USDRUB | 20.04 | 18.60 | 83.28 | 0.46 |
| USDZAR | 1.44 | 17.15 | 84.29 | 0.13 |

Where the two disagree the naive rule is usually earlier by construction (a percentile flips the day vol crosses it) while the HMM waits for the transition to be likely — it trades a few days of lag for far fewer flickers (compare mean durations above). Dated episodes (full history) where both flagged stress within 15 trading days of each other (lead_days > 0 = HMM first); the three largest HMM leads are shown:

**USDMXN** — 17 matched episodes; HMM led in 2, naive led in 10, same day 5.

| hmm_start | naive_start | lead_days |
|---|---|---|
| 2025-04-07 | 2025-04-14 | 5 |
| 2025-04-10 | 2025-04-14 | 2 |
| 2023-03-14 | 2023-03-14 | 0 |

**USDBRL** — 19 matched episodes; HMM led in 5, naive led in 8, same day 6.

| hmm_start | naive_start | lead_days |
|---|---|---|
| 2011-09-23 | 2011-10-13 | 14 |
| 2017-06-13 | 2017-07-03 | 14 |
| 2022-05-16 | 2022-06-02 | 13 |

**USDZAR** — 8 matched episodes; HMM led in 2, naive led in 5, same day 1.

| hmm_start | naive_start | lead_days |
|---|---|---|
| 2016-02-04 | 2016-02-25 | 15 |
| 2011-11-11 | 2011-12-01 | 14 |
| 2016-06-27 | 2016-06-27 | 0 |

**USDPLN** — 7 matched episodes; HMM led in 1, naive led in 3, same day 3.

| hmm_start | naive_start | lead_days |
|---|---|---|
| 2010-12-03 | 2010-12-06 | 1 |
| 2006-05-15 | 2006-05-15 | 0 |
| 2008-08-26 | 2008-08-26 | 0 |

**USDRUB** — 15 matched episodes; HMM led in 4, naive led in 2, same day 9.

| hmm_start | naive_start | lead_days |
|---|---|---|
| 2015-12-11 | 2015-12-29 | 12 |
| 2016-01-20 | 2016-01-25 | 3 |
| 2026-03-23 | 2026-03-24 | 1 |

Verdict: the HMM does **not** systematically lead the naive rule — across all matched episodes it led in 14 and lagged in 28. When it leads it can be by several days (EURUSD, autumn 2011), but more often it is simultaneous or later. Its value is not earlier warnings but a four-way, sticky, probabilistic description (with confidence and entropy) instead of a binary flicker — and that is what the forecaster and narrator consume.

## 4. Economic meaning: a toy trend rule inside each regime (out of sample)

MA(50/200) long/short decided at t, earned at t+1, gross of costs — a diagnostic only. Claim under test: trend-following should look best in `trend` and worst in `chop`.

**USDMXN**

| regime | days | sharpe | ann_ret_pct |
|---|---|---|---|
| calm | 547 | -0.14 | -1.06 |
| trend | 888 | -0.44 | -5.64 |
| chop | 769 | -0.62 | -6.70 |
| crisis | 301 | -0.91 | -16.42 |
| ALL | 2505 | -0.52 | -6.26 |

**USDBRL**

| regime | days | sharpe | ann_ret_pct |
|---|---|---|---|
| calm | 992 | 0.54 | 6.86 |
| trend | 303 | -0.73 | -13.69 |
| chop | 1129 | -0.50 | -8.38 |
| crisis | 78 | 3.47 | 70.72 |
| ALL | 2502 | -0.03 | -0.52 |

**USDZAR**

| regime | days | sharpe | ann_ret_pct |
|---|---|---|---|
| calm | 748 | -0.24 | -2.86 |
| trend | 637 | -0.79 | -12.35 |
| chop | 1079 | 0.40 | 5.82 |
| crisis | 36 | 1.59 | 41.05 |
| ALL | 2500 | -0.06 | -0.90 |

**USDPLN**

| regime | days | sharpe | ann_ret_pct |
|---|---|---|---|
| calm | 1353 | -0.58 | -4.81 |
| trend | 946 | 0.28 | 2.96 |
| chop | 161 | 0.20 | 3.04 |
| crisis | 43 | -2.25 | -42.94 |
| ALL | 2503 | -0.20 | -2.02 |

**USDRUB**

| regime | days | sharpe | ann_ret_pct |
|---|---|---|---|
| calm | 202 | -0.51 | -3.97 |
| trend | 1017 | -0.48 | -8.55 |
| chop | 780 | -0.16 | -1.77 |
| crisis | 500 | -0.32 | -16.35 |
| ALL | 2499 | -0.29 | -7.62 |

Reading: USDMXN: best in `calm`, worst in `crisis`; USDBRL: best in `crisis`, worst in `trend`; USDZAR: best in `crisis`, worst in `trend`; USDPLN: best in `trend`, worst in `crisis`; USDRUB: best in `chop`, worst in `calm`. The claim holds for 1/3 pairs on 'best in trend' and 0/3 on 'worst in chop' — it does **not** hold as a general pattern, and `crisis` is where a moving-average rule gets whipsawed hardest. Differences between labels are also within noise for these sample sizes. The regimes are descriptive states of volatility/momentum, not a trading edge, and this report says so.

## 5. Plots

![USDMXN timeline](regimes_timeline_USDMXN.png)

![USDBRL timeline](regimes_timeline_USDBRL.png)

![USDZAR timeline](regimes_timeline_USDZAR.png)

![USDPLN timeline](regimes_timeline_USDPLN.png)

![USDRUB timeline](regimes_timeline_USDRUB.png)

![durations](regime_durations.png)

## 6. Limitations

- **Daily data only.** Intraday storms are averaged away; Yahoo's daily close is a start-of-day snapshot, so returns are one day late relative to highs/lows.
- **Label noise.** Filtered labels flicker near state boundaries and the trend/chop split is seed-sensitive (section 2). Read `regime_prob` and `hmm_entropy` with the label.
- **Descriptive, not predictive.** A regime describes the recent past; the transition matrix says regimes are sticky, nothing more. Direction is not modelled anywhere.
- **Frozen naming rule + rare events.** One extreme episode (SNB 2015) can own a whole state (USDCHF); the rule then mislabels the ordinary stress state.
- **Single training window (2005–2016).** Post-2016 structure (2020, 2022) is scored, not learnt; a monthly expanding refit is the phase-06 plan.
- **Gaussian emissions.** Fat tails are absorbed by the high-vol state rather than modelled.


_Educational tool. Not investment advice._
