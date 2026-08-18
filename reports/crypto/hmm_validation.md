# HMM validation — are these regimes real, stable and useful?

_Generated 2026-08-18 13:09. Train = dates ≤ 2020-12-31; out-of-sample (OOS) = 2021-01-01 onward — nothing after the train end touched the fit. All regime labels are FILTERED (causal)._

## 1. Regime anatomy (train vs out-of-sample)

Frequency, mean run length, annualised vol of daily returns, mean daily return (bp) and worst drawdown of the return stream *inside* each label. Ordering by vol is by construction (calm < … < crisis); everything else is a genuine test.

**BTC-USD**

| period | regime | days | freq_pct | mean_duration_d | ann_vol_pct | mean_ret_bp | worst_dd_pct |
|---|---|---|---|---|---|---|---|
| oos | calm | 674 | 32.80 | 18.72 | 32.75 | 4.61 | -19.47 |
| oos | trend | 332 | 16.16 | 9.76 | 69.08 | 12.51 | -54.32 |
| oos | chop | 781 | 38.00 | 16.62 | 52.47 | -0.68 | -59.33 |
| oos | crisis | 268 | 13.04 | 16.75 | 91.98 | 4.72 | -53.55 |
| train | calm | 602 | 26.90 | 20.07 | 28.40 | 30.69 | -12.23 |
| train | trend | 691 | 30.88 | 13.82 | 82.63 | 57.74 | -34.50 |
| train | chop | 545 | 24.35 | 13.62 | 47.68 | -8.59 | -55.04 |
| train | crisis | 400 | 17.87 | 21.05 | 120.40 | -25.59 | -77.27 |

**ETH-USD**

| period | regime | days | freq_pct | mean_duration_d | ann_vol_pct | mean_ret_bp | worst_dd_pct |
|---|---|---|---|---|---|---|---|
| oos | calm | 1221 | 59.42 | 33.00 | 55.44 | -1.96 | -75.56 |
| oos | trend | 467 | 22.73 | 16.68 | 92.05 | 50.35 | -36.48 |
| oos | chop | 321 | 15.62 | 12.84 | 99.39 | -21.75 | -74.25 |
| oos | crisis | 46 | 2.24 | 11.50 | 167.61 | -100.23 | -41.05 |
| train | calm | 402 | 36.91 | 17.48 | 59.12 | -0.77 | -61.66 |
| train | trend | 359 | 32.97 | 17.10 | 99.18 | 50.09 | -37.98 |
| train | chop | 258 | 23.69 | 18.43 | 104.51 | -65.92 | -83.81 |
| train | crisis | 70 | 6.43 | 14.00 | 181.82 | -73.30 | -62.48 |

**LTC-USD**

| period | regime | days | freq_pct | mean_duration_d | ann_vol_pct | mean_ret_bp | worst_dd_pct |
|---|---|---|---|---|---|---|---|
| oos | calm | 667 | 32.46 | 17.10 | 41.92 | -2.51 | -40.74 |
| oos | trend | 582 | 28.32 | 14.20 | 93.56 | 17.38 | -67.03 |
| oos | chop | 691 | 33.63 | 14.70 | 79.57 | -11.29 | -76.21 |
| oos | crisis | 115 | 5.60 | 8.85 | 179.98 | -95.09 | -82.17 |
| train | calm | 579 | 25.87 | 22.27 | 33.08 | 0.10 | -19.77 |
| train | trend | 683 | 30.52 | 18.46 | 97.43 | 35.97 | -54.74 |
| train | chop | 611 | 27.30 | 19.09 | 83.12 | -50.62 | -95.40 |
| train | crisis | 365 | 16.31 | 24.33 | 200.59 | 112.51 | -64.61 |

Reading: the vol ordering survives out of sample for every pair (a label is not just an in-sample artefact). Mean returns inside labels are tiny relative to vol — regimes describe *conditions*, not direction. Note USDCHF: its `crisis` state was learnt almost entirely from the January-2015 SNB shock (20 train days, ~65 % annualised vol) and never fires out of sample; USDCHF's 2008–2011 stress carries the `chop` name instead. This is a labelling artefact of the frozen naming rule plus one extreme event, and it is reported rather than patched.

## 2. Seed stability

The seed-42 model is the reference; each cell is the share of days on which a model refit with another seed (same data, same naming rule) gives the same label.

| pair | 1 | 2 | 3 | 4 | 5 | mean |
|---|---|---|---|---|---|---|
| BTC-USD | 0.980 | 0.979 | 0.809 | 1.000 | 0.659 | 0.885 |
| ETH-USD | 0.788 | 0.999 | 0.645 | 0.927 | 0.743 | 0.821 |
| LTC-USD | 0.685 | 1.000 | 0.685 | 0.999 | 1.000 | 0.874 |

Interpretation, honestly: agreement ranges from 65% to 100%. Some refits land on the same optimum (≥ 99 % agreement) and others on a different one where the middle two states split the data differently — ETH-USD is the least stable (mean 82%, below the 80 % warning threshold). The calm/crisis ends are the stable part; the trend/chop split is the fragile part. EM finds local optima, and a rule that names states by mean vol/momentum inherits that. Practical consequences: (a) treat `trend` vs `chop` as soft; (b) a production refit should use several restarts and keep the best likelihood, and be checked against the previous labelling before it replaces it (phase 06 refit path); (c) `regime_prob`/`hmm_entropy` are more trustworthy than the label itself.

## 3. Baseline: does the HMM add anything to a one-line vol rule?

Naive rule: *stressed* when vol_20 is above its trailing 250-day 80th percentile, else *quiet* (causal). Compared with HMM `crisis` out of sample.

| pair | hmm_crisis_pct | naive_stress_pct | agreement_pct | kappa |
|---|---|---|---|---|
| BTC-USD | 13.04 | 20.83 | 85.69 | 0.50 |
| ETH-USD | 2.24 | 18.69 | 83.36 | 0.17 |
| LTC-USD | 5.60 | 18.39 | 85.35 | 0.33 |

Where the two disagree the naive rule is usually earlier by construction (a percentile flips the day vol crosses it) while the HMM waits for the transition to be likely — it trades a few days of lag for far fewer flickers (compare mean durations above). Dated episodes (full history) where both flagged stress within 15 trading days of each other (lead_days > 0 = HMM first); the three largest HMM leads are shown:

**BTC-USD** — 24 matched episodes; HMM led in 6, naive led in 9, same day 9.

| hmm_start | naive_start | lead_days |
|---|---|---|
| 2024-04-02 | 2024-04-17 | 15 |
| 2015-01-03 | 2015-01-14 | 11 |
| 2021-05-04 | 2021-05-12 | 8 |

**ETH-USD** — 6 matched episodes; HMM led in 0, naive led in 5, same day 1.

| hmm_start | naive_start | lead_days |
|---|---|---|
| 2022-11-09 | 2022-11-09 | 0 |
| 2018-12-23 | 2018-12-21 | -2 |
| 2020-03-12 | 2020-03-08 | -4 |

**LTC-USD** — 19 matched episodes; HMM led in 7, naive led in 4, same day 8.

| hmm_start | naive_start | lead_days |
|---|---|---|
| 2021-09-07 | 2021-09-20 | 13 |
| 2018-02-01 | 2018-02-14 | 13 |
| 2017-09-01 | 2017-09-11 | 10 |

Verdict: the HMM does **not** systematically lead the naive rule — across all matched episodes it led in 13 and lagged in 18. When it leads it can be by several days (EURUSD, autumn 2011), but more often it is simultaneous or later. Its value is not earlier warnings but a four-way, sticky, probabilistic description (with confidence and entropy) instead of a binary flicker — and that is what the forecaster and narrator consume.

## 4. Economic meaning: a toy trend rule inside each regime (out of sample)

MA(50/200) long/short decided at t, earned at t+1, gross of costs — a diagnostic only. Claim under test: trend-following should look best in `trend` and worst in `chop`.

**BTC-USD**

| regime | days | sharpe | ann_ret_pct |
|---|---|---|---|
| calm | 673 | -0.75 | -30.64 |
| trend | 332 | 1.52 | 97.15 |
| chop | 781 | -0.08 | -4.33 |
| crisis | 268 | 0.71 | 55.43 |
| ALL | 2054 | 0.20 | 11.25 |

**ETH-USD**

| regime | days | sharpe | ann_ret_pct |
|---|---|---|---|
| calm | 1220 | -0.15 | -9.34 |
| trend | 467 | 0.61 | 56.39 |
| chop | 321 | 1.09 | 96.38 |
| crisis | 46 | 0.60 | 78.52 |
| ALL | 2054 | 0.31 | 24.09 |

**LTC-USD**

| regime | days | sharpe | ann_ret_pct |
|---|---|---|---|
| calm | 666 | -0.98 | -57.38 |
| trend | 582 | 0.04 | 3.94 |
| chop | 691 | 0.22 | 17.47 |
| crisis | 115 | -2.28 | -328.27 |
| ALL | 2054 | -0.36 | -29.99 |

Reading: BTC-USD: best in `trend`, worst in `calm`; ETH-USD: best in `chop`, worst in `calm`; LTC-USD: best in `chop`, worst in `crisis`. The claim holds for 1/3 pairs on 'best in trend' and 0/3 on 'worst in chop' — it does **not** hold as a general pattern, and `crisis` is where a moving-average rule gets whipsawed hardest. Differences between labels are also within noise for these sample sizes. The regimes are descriptive states of volatility/momentum, not a trading edge, and this report says so.

## 5. Plots

![BTC-USD timeline](regimes_timeline_BTC-USD.png)

![ETH-USD timeline](regimes_timeline_ETH-USD.png)

![LTC-USD timeline](regimes_timeline_LTC-USD.png)

![durations](regime_durations.png)

## 6. Limitations

- **Daily data only.** Intraday storms are averaged away; Yahoo's daily close is a start-of-day snapshot, so returns are one day late relative to highs/lows.
- **Label noise.** Filtered labels flicker near state boundaries and the trend/chop split is seed-sensitive (section 2). Read `regime_prob` and `hmm_entropy` with the label.
- **Descriptive, not predictive.** A regime describes the recent past; the transition matrix says regimes are sticky, nothing more. Direction is not modelled anywhere.
- **Frozen naming rule + rare events.** One extreme episode (SNB 2015) can own a whole state (USDCHF); the rule then mislabels the ordinary stress state.
- **Single training window (2005–2016).** Post-2016 structure (2020, 2022) is scored, not learnt; a monthly expanding refit is the phase-06 plan.
- **Gaussian emissions.** Fat tails are absorbed by the high-vol state rather than modelled.


_Educational tool. Not investment advice._
