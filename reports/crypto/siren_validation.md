# Siren validation — does it scream at the famous shocks?

_Generated 2026-08-19 17:39. Autoencoder (8, 3, 8), trained on 2041 calm train days (2018-03-02 → 2020-12-29, regime_prob > 0.7), pooled across pairs, no pair identity. anomaly_pct = percentile of the reconstruction error against that calm-train distribution._

## BTC-USD — 15 loudest days

| date | anomaly_score | anomaly_pct |
|---|---|---|
| 2020-03-12 | 14.35 | 100.00 |
| 2020-03-19 | 7.61 | 100.00 |
| 2021-02-22 | 7.34 | 100.00 |
| 2020-03-30 | 7.15 | 100.00 |
| 2020-03-31 | 6.68 | 100.00 |
| 2020-03-29 | 6.24 | 100.00 |
| 2021-01-15 | 6.13 | 100.00 |
| 2020-03-13 | 6.12 | 100.00 |
| 2019-10-27 | 6.03 | 100.00 |
| 2020-03-28 | 5.98 | 100.00 |
| 2021-01-16 | 5.81 | 100.00 |
| 2020-03-23 | 5.72 | 100.00 |
| 2024-08-08 | 5.70 | 100.00 |
| 2020-03-17 | 5.52 | 100.00 |
| 2021-02-13 | 5.49 | 100.00 |

- **COVID 'Black Thursday' (2020-03-12)**: peak anomaly_pct 100.0 within [−1, +3] days, rank 1 of 3145 days for this pair → ✅ lights up.

- **FTX collapse (2022-11-09)**: peak anomaly_pct 99.7 within [−1, +3] days, rank 67 of 3145 days for this pair → ✅ lights up.

## ETH-USD — 15 loudest days

| date | anomaly_score | anomaly_pct |
|---|---|---|
| 2020-03-12 | 22.25 | 100.00 |
| 2021-05-24 | 13.36 | 100.00 |
| 2021-01-06 | 11.44 | 100.00 |
| 2020-03-30 | 10.74 | 100.00 |
| 2020-03-31 | 10.63 | 100.00 |
| 2020-03-19 | 10.11 | 100.00 |
| 2021-01-11 | 9.54 | 100.00 |
| 2021-01-21 | 9.48 | 100.00 |
| 2021-01-07 | 9.46 | 100.00 |
| 2020-03-26 | 9.42 | 100.00 |
| 2020-03-13 | 9.42 | 100.00 |
| 2020-03-29 | 9.41 | 100.00 |
| 2020-03-27 | 9.34 | 100.00 |
| 2020-03-25 | 9.08 | 100.00 |
| 2020-03-24 | 9.00 | 100.00 |

- **May 2021 crash (2021-05-19)**: peak anomaly_pct 100.0 within [−1, +3] days, rank 18 of 3145 days for this pair → ✅ lights up.

- **Terra/LUNA collapse (2022-05-12)**: peak anomaly_pct 98.8 within [−1, +3] days, rank 365 of 3145 days for this pair → ✅ lights up.

## XRP-USD — 15 loudest days

| date | anomaly_score | anomaly_pct |
|---|---|---|
| 2024-12-02 | 69.42 | 100.00 |
| 2024-12-01 | 58.49 | 100.00 |
| 2018-01-08 | 53.56 | 100.00 |
| 2021-04-13 | 53.54 | 100.00 |
| 2020-11-24 | 53.05 | 100.00 |
| 2024-12-03 | 52.87 | 100.00 |
| 2021-04-14 | 50.21 | 100.00 |
| 2024-11-30 | 38.31 | 100.00 |
| 2020-11-23 | 36.48 | 100.00 |
| 2018-09-22 | 34.76 | 100.00 |
| 2021-04-15 | 34.63 | 100.00 |
| 2023-07-13 | 34.04 | 100.00 |
| 2024-11-29 | 33.04 | 100.00 |
| 2020-11-25 | 31.57 | 100.00 |
| 2021-04-16 | 29.68 | 100.00 |

- **SEC lawsuit filed (2020-12-23)**: peak anomaly_pct 100.0 within [−1, +3] days, rank 21 of 3145 days for this pair → ✅ lights up.

- **SEC ruling (2023-07-13)**: peak anomaly_pct 100.0 within [−1, +3] days, rank 12 of 3145 days for this pair → ✅ lights up.

## BNB-USD — 15 loudest days

| date | anomaly_score | anomaly_pct |
|---|---|---|
| 2021-02-19 | 330.24 | 100.00 |
| 2021-02-20 | 187.98 | 100.00 |
| 2021-02-21 | 173.41 | 100.00 |
| 2021-02-22 | 134.62 | 100.00 |
| 2018-01-11 | 114.69 | 100.00 |
| 2018-01-12 | 102.76 | 100.00 |
| 2021-02-24 | 97.64 | 100.00 |
| 2021-02-23 | 97.28 | 100.00 |
| 2021-02-18 | 91.05 | 100.00 |
| 2018-01-13 | 83.80 | 100.00 |
| 2021-02-17 | 57.71 | 100.00 |
| 2021-02-25 | 56.89 | 100.00 |
| 2021-02-12 | 46.68 | 100.00 |
| 2021-02-10 | 45.19 | 100.00 |
| 2018-01-09 | 45.04 | 100.00 |

- **SEC v. Binance (2023-06-05)**: peak anomaly_pct 88.6 within [−1, +3] days, rank 1030 of 3145 days for this pair → ❌ does NOT light up.

- **FTX collapse (2022-11-09)**: peak anomaly_pct 99.9 within [−1, +3] days, rank 144 of 3145 days for this pair → ✅ lights up.

## ADA-USD — 15 loudest days

| date | anomaly_score | anomaly_pct |
|---|---|---|
| 2021-02-10 | 38.02 | 100.00 |
| 2021-02-20 | 35.73 | 100.00 |
| 2024-11-23 | 33.14 | 100.00 |
| 2024-11-24 | 31.24 | 100.00 |
| 2025-03-02 | 29.71 | 100.00 |
| 2024-11-22 | 25.81 | 100.00 |
| 2021-02-16 | 25.24 | 100.00 |
| 2021-01-06 | 24.62 | 100.00 |
| 2021-02-21 | 23.99 | 100.00 |
| 2021-02-18 | 23.64 | 100.00 |
| 2024-11-25 | 23.60 | 100.00 |
| 2021-02-19 | 20.99 | 100.00 |
| 2021-02-17 | 20.64 | 100.00 |
| 2024-11-10 | 19.57 | 100.00 |
| 2021-02-11 | 19.35 | 100.00 |

- **May 2021 crash (2021-05-19)**: peak anomaly_pct 100.0 within [−1, +3] days, rank 46 of 3144 days for this pair → ✅ lights up.

- **Terra/LUNA collapse (2022-05-12)**: peak anomaly_pct 100.0 within [−1, +3] days, rank 155 of 3144 days for this pair → ✅ lights up.

## March 2020, all pairs

Share of March-2020 days above the 98th calm-train percentile: ADA-USD 65%, BNB-USD 65%, BTC-USD 65%, ETH-USD 68%, XRP-USD 61%.

## Sparkline
![anomaly](siren_anomaly_pct.png)

## Honest reading

NOT every named shock lights up: BNB-USD SEC v. Binance peaks at 89. Yahoo's daily close is a start-of-day snapshot, so a shock's return shows one day late while the intraday range shows on the day — the [−1, +3]-day window accounts for that. The siren is a detector, not a predictor: it says 'today looks unlike any calm day I learnt from', and it says it about many days that were merely volatile, not historic. Read it with the regime and the change risk, not instead of them.


_Educational tool. Not investment advice._
