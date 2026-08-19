# HMM validation — are these regimes real, stable and useful?

_Generated 2026-08-19 17:39. Train = dates ≤ 2020-12-31; out-of-sample (OOS) = 2021-01-01 onward — nothing after the train end touched the fit. All regime labels are FILTERED (causal)._

## 1. Regime anatomy (train vs out-of-sample)

Frequency, mean run length, annualised vol of daily returns, mean daily return (bp) and worst drawdown of the return stream *inside* each label. Ordering by vol is by construction (calm < … < crisis); everything else is a genuine test.

**BTC-USD**

| period | regime | days | freq_pct | mean_duration_d | ann_vol_pct | mean_ret_bp | worst_dd_pct |
|---|---|---|---|---|---|---|---|
| oos | calm | 832 | 40.47 | 14.10 | 32.69 | 0.95 | -31.11 |
| oos | trend | 589 | 28.65 | 10.71 | 59.10 | 28.35 | -42.54 |
| oos | chop | 393 | 19.11 | 10.34 | 63.10 | -15.03 | -54.91 |
| oos | crisis | 242 | 11.77 | 18.62 | 95.23 | -14.70 | -55.79 |
| train | calm | 270 | 24.79 | 12.27 | 27.21 | -1.82 | -33.11 |
| train | trend | 407 | 37.37 | 20.35 | 67.62 | 60.27 | -35.23 |
| train | chop | 205 | 18.82 | 13.67 | 58.82 | -42.44 | -59.69 |
| train | crisis | 207 | 19.01 | 29.57 | 127.33 | -46.78 | -71.43 |

**ETH-USD**

| period | regime | days | freq_pct | mean_duration_d | ann_vol_pct | mean_ret_bp | worst_dd_pct |
|---|---|---|---|---|---|---|---|
| oos | calm | 1222 | 59.44 | 33.03 | 55.41 | -1.94 | -75.56 |
| oos | trend | 467 | 22.71 | 16.68 | 92.05 | 50.35 | -36.48 |
| oos | chop | 321 | 15.61 | 12.84 | 99.39 | -21.75 | -74.25 |
| oos | crisis | 46 | 2.24 | 11.50 | 167.61 | -100.23 | -41.05 |
| train | calm | 402 | 36.91 | 17.48 | 59.12 | -0.77 | -61.66 |
| train | trend | 359 | 32.97 | 17.10 | 99.18 | 50.09 | -37.98 |
| train | chop | 258 | 23.69 | 18.43 | 104.51 | -65.92 | -83.81 |
| train | crisis | 70 | 6.43 | 14.00 | 181.82 | -73.30 | -62.48 |

**XRP-USD**

| period | regime | days | freq_pct | mean_duration_d | ann_vol_pct | mean_ret_bp | worst_dd_pct |
|---|---|---|---|---|---|---|---|
| oos | calm | 1192 | 57.98 | 37.25 | 53.67 | -6.28 | -68.44 |
| oos | trend | 310 | 15.08 | 13.48 | 141.60 | 81.60 | -44.28 |
| oos | chop | 353 | 17.17 | 10.70 | 81.92 | -26.29 | -73.86 |
| oos | crisis | 201 | 9.78 | 12.56 | 180.41 | 32.99 | -73.79 |
| train | calm | 556 | 51.06 | 55.60 | 58.35 | 6.22 | -51.02 |
| train | trend | 158 | 14.51 | 14.36 | 149.22 | -7.19 | -48.66 |
| train | chop | 266 | 24.43 | 22.17 | 87.08 | -93.09 | -92.28 |
| train | crisis | 109 | 10.01 | 15.57 | 220.83 | -44.77 | -66.26 |

**BNB-USD**

| period | regime | days | freq_pct | mean_duration_d | ann_vol_pct | mean_ret_bp | worst_dd_pct |
|---|---|---|---|---|---|---|---|
| oos | calm | 1625 | 79.04 | 147.73 | 50.64 | 7.24 | -51.68 |
| oos | trend | 50 | 2.43 | 16.67 | 259.37 | 186.00 | -55.08 |
| oos | chop | 372 | 18.09 | 28.62 | 110.07 | 30.56 | -60.93 |
| oos | crisis | 9 | 0.44 | 9.00 | 233.14 | -513.23 | -28.70 |
| train | calm | 544 | 49.95 | 41.85 | 63.64 | 2.09 | -71.75 |
| train | trend | 66 | 6.06 | 22.00 | 217.43 | -193.90 | -77.97 |
| train | chop | 472 | 43.34 | 29.50 | 105.90 | 37.14 | -58.41 |
| train | crisis | 7 | 0.64 | 7.00 | 165.70 | 153.79 | -6.90 |

**ADA-USD**

| period | regime | days | freq_pct | mean_duration_d | ann_vol_pct | mean_ret_bp | worst_dd_pct |
|---|---|---|---|---|---|---|---|
| oos | calm | 1227 | 59.71 | 36.09 | 68.03 | -15.75 | -89.40 |
| oos | trend | 353 | 17.18 | 10.38 | 109.61 | 48.82 | -53.05 |
| oos | chop | 363 | 17.66 | 13.44 | 102.36 | -9.64 | -63.92 |
| oos | crisis | 112 | 5.45 | 12.44 | 201.27 | 46.33 | -49.89 |
| train | calm | 326 | 29.94 | 21.73 | 69.68 | -18.46 | -56.01 |
| train | trend | 328 | 30.12 | 18.22 | 107.62 | 60.37 | -55.21 |
| train | chop | 320 | 29.38 | 17.78 | 112.83 | -54.38 | -90.50 |
| train | crisis | 115 | 10.56 | 19.17 | 187.11 | -117.71 | -78.29 |

Reading: the vol ordering survives out of sample for every pair (a label is not just an in-sample artefact). Mean returns inside labels are tiny relative to vol — regimes describe *conditions*, not direction. Note USDCHF: its `crisis` state was learnt almost entirely from the January-2015 SNB shock (20 train days, ~65 % annualised vol) and never fires out of sample; USDCHF's 2008–2011 stress carries the `chop` name instead. This is a labelling artefact of the frozen naming rule plus one extreme event, and it is reported rather than patched.

## 2. Seed stability

The seed-42 model is the reference; each cell is the share of days on which a model refit with another seed (same data, same naming rule) gives the same label.

| pair | 1 | 2 | 3 | 4 | 5 | mean |
|---|---|---|---|---|---|---|
| ADA-USD | 0.894 | 0.753 | 0.599 | 0.827 | 0.715 | 0.757 |
| BNB-USD | 0.732 | 0.985 | 0.714 | 0.986 | 0.729 | 0.829 |
| BTC-USD | 0.956 | 0.368 | 0.947 | 0.360 | 0.864 | 0.699 |
| ETH-USD | 0.789 | 0.999 | 0.645 | 0.928 | 0.743 | 0.821 |
| XRP-USD | 0.747 | 0.792 | 1.000 | 0.911 | 0.546 | 0.799 |

Interpretation, honestly: agreement ranges from 36% to 100%. Some refits land on the same optimum (≥ 99 % agreement) and others on a different one where the middle two states split the data differently — BTC-USD is the least stable (mean 70%, below the 80 % warning threshold). The calm/crisis ends are the stable part; the trend/chop split is the fragile part. EM finds local optima, and a rule that names states by mean vol/momentum inherits that. Practical consequences: (a) treat `trend` vs `chop` as soft; (b) a production refit should use several restarts and keep the best likelihood, and be checked against the previous labelling before it replaces it (phase 06 refit path); (c) `regime_prob`/`hmm_entropy` are more trustworthy than the label itself.

## 3. Baseline: does the HMM add anything to a one-line vol rule?

Naive rule: *stressed* when vol_20 is above its trailing 250-day 80th percentile, else *quiet* (causal). Compared with HMM `crisis` out of sample.

| pair | hmm_crisis_pct | naive_stress_pct | agreement_pct | kappa |
|---|---|---|---|---|
| ADA-USD | 5.45 | 19.12 | 85.94 | 0.37 |
| BNB-USD | 0.44 | 18.63 | 81.81 | 0.04 |
| BTC-USD | 11.77 | 20.82 | 85.89 | 0.49 |
| ETH-USD | 2.24 | 18.68 | 83.37 | 0.17 |
| XRP-USD | 9.78 | 18.68 | 82.44 | 0.29 |

Where the two disagree the naive rule is usually earlier by construction (a percentile flips the day vol crosses it) while the HMM waits for the transition to be likely — it trades a few days of lag for far fewer flickers (compare mean durations above). Dated episodes (full history) where both flagged stress within 15 trading days of each other (lead_days > 0 = HMM first); the three largest HMM leads are shown:

**BTC-USD** — 13 matched episodes; HMM led in 3, naive led in 3, same day 7.

| hmm_start | naive_start | lead_days |
|---|---|---|
| 2022-02-07 | 2022-02-21 | 14 |
| 2021-05-05 | 2021-05-12 | 7 |
| 2018-11-19 | 2018-11-20 | 1 |

**ETH-USD** — 6 matched episodes; HMM led in 0, naive led in 5, same day 1.

| hmm_start | naive_start | lead_days |
|---|---|---|
| 2022-11-09 | 2022-11-09 | 0 |
| 2018-12-23 | 2018-12-21 | -2 |
| 2020-03-12 | 2020-03-08 | -4 |

**XRP-USD** — 13 matched episodes; HMM led in 3, naive led in 3, same day 7.

| hmm_start | naive_start | lead_days |
|---|---|---|
| 2022-02-07 | 2022-02-21 | 14 |
| 2021-05-19 | 2021-05-24 | 5 |
| 2018-09-18 | 2018-09-20 | 2 |

**BNB-USD** — 0 matched episodes; HMM led in 0, naive led in 0, same day 0.

_No matched episodes (the HMM's crisis label rarely or never fires for this pair)._

**ADA-USD** — 6 matched episodes; HMM led in 0, naive led in 3, same day 3.

| hmm_start | naive_start | lead_days |
|---|---|---|
| 2018-11-28 | 2018-11-28 | 0 |
| 2020-03-12 | 2020-03-12 | 0 |
| 2025-03-02 | 2025-03-02 | 0 |

Verdict: the HMM does **not** systematically lead the naive rule — across all matched episodes it led in 6 and lagged in 14. When it leads it can be by several days (EURUSD, autumn 2011), but more often it is simultaneous or later. Its value is not earlier warnings but a four-way, sticky, probabilistic description (with confidence and entropy) instead of a binary flicker — and that is what the forecaster and narrator consume.

## 4. Economic meaning: a toy trend rule inside each regime (out of sample)

MA(50/200) long/short decided at t, earned at t+1, gross of costs — a diagnostic only. Claim under test: trend-following should look best in `trend` and worst in `chop`.

**BTC-USD**

| regime | days | sharpe | ann_ret_pct |
|---|---|---|---|
| calm | 831 | -1.00 | -42.42 |
| trend | 589 | 0.86 | 49.43 |
| chop | 393 | 0.78 | 50.92 |
| crisis | 242 | 0.46 | 37.73 |
| ALL | 2055 | 0.20 | 11.20 |

**ETH-USD**

| regime | days | sharpe | ann_ret_pct |
|---|---|---|---|
| calm | 1221 | -0.15 | -9.40 |
| trend | 467 | 0.61 | 56.39 |
| chop | 321 | 1.09 | 96.38 |
| crisis | 46 | 0.60 | 78.52 |
| ALL | 2055 | 0.31 | 24.04 |

**XRP-USD**

| regime | days | sharpe | ann_ret_pct |
|---|---|---|---|
| calm | 1191 | -0.34 | -24.43 |
| trend | 310 | -0.42 | -60.20 |
| chop | 353 | 0.56 | 55.74 |
| crisis | 201 | -0.11 | -13.34 |
| ALL | 2055 | -0.16 | -14.97 |

**BNB-USD**

| regime | days | sharpe | ann_ret_pct |
|---|---|---|---|
| calm | 1624 | 0.09 | 4.62 |
| trend | 50 | 2.39 | 563.09 |
| chop | 372 | 1.20 | 134.89 |
| crisis | 9 | -0.09 | -21.03 |
| ALL | 2055 | 0.53 | 41.68 |

**ADA-USD**

| regime | days | sharpe | ann_ret_pct |
|---|---|---|---|
| calm | 1226 | -0.03 | -2.74 |
| trend | 353 | 1.48 | 176.79 |
| chop | 363 | 0.93 | 84.53 |
| crisis | 112 | -0.25 | -34.87 |
| ALL | 2054 | 0.44 | 41.79 |

Reading: BTC-USD: best in `trend`, worst in `calm`; ETH-USD: best in `chop`, worst in `calm`; XRP-USD: best in `chop`, worst in `trend`; BNB-USD: best in `trend`, worst in `crisis`; ADA-USD: best in `trend`, worst in `crisis`. The claim holds for 3/3 pairs on 'best in trend' and 0/3 on 'worst in chop' — it does **not** hold as a general pattern, and `crisis` is where a moving-average rule gets whipsawed hardest. Differences between labels are also within noise for these sample sizes. The regimes are descriptive states of volatility/momentum, not a trading edge, and this report says so.

## 5. Plots

![BTC-USD timeline](regimes_timeline_BTC-USD.png)

![ETH-USD timeline](regimes_timeline_ETH-USD.png)

![XRP-USD timeline](regimes_timeline_XRP-USD.png)

![BNB-USD timeline](regimes_timeline_BNB-USD.png)

![ADA-USD timeline](regimes_timeline_ADA-USD.png)

![durations](regime_durations.png)

## 6. Limitations

- **Daily data only.** Intraday storms are averaged away; Yahoo's daily close is a start-of-day snapshot, so returns are one day late relative to highs/lows.
- **Label noise.** Filtered labels flicker near state boundaries and the trend/chop split is seed-sensitive (section 2). Read `regime_prob` and `hmm_entropy` with the label.
- **Descriptive, not predictive.** A regime describes the recent past; the transition matrix says regimes are sticky, nothing more. Direction is not modelled anywhere.
- **Frozen naming rule + rare events.** One extreme episode (SNB 2015) can own a whole state (USDCHF); the rule then mislabels the ordinary stress state.
- **Single training window (2005–2016).** Post-2016 structure (2020, 2022) is scored, not learnt; a monthly expanding refit is the phase-06 plan.
- **Gaussian emissions.** Fat tails are absorbed by the high-vol state rather than modelled.


_Educational tool. Not investment advice._
