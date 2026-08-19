# Central-bank communication index — Stage 1 event study (lexicon leg)

Generated 2026-08-19 14:10 UTC · lexicon v1 · 184 statements on disk · Educational tool. Not investment advice.

## Corpus (official statements only, fetched from the four banks' own sites)

| bank | n | first | last | mean tone | sd tone | mean uncertainty | sd surprise |
|---|---|---|---|---|---|---|---|
| BOE | 50 | 2020-01-30 | 2026-07-30 | +0.017 | 0.364 | 0.0149 | 0.310 |
| ECB | 53 | 2020-01-23 | 2026-07-23 | -0.197 | 0.580 | 0.0063 | 0.354 |
| FOMC | 55 | 2020-01-29 | 2026-07-29 | +0.273 | 0.496 | 0.0148 | 0.504 |
| SNB | 26 | 2020-03-19 | 2026-06-18 | -0.167 | 0.309 | 0.0195 | 0.284 |

Statements since the deploy date (2026-08-17): **0** — FOMC 0, ECB 0, SNB 0, BOE 0. FinBERT / LLM scores exist only for these (none yet if 0).

## Event study: |tone surprise| vs what followed (no direction, ever)

Design: anchor = trading day the statement became known; vol_change = log(mean |ret| t+1..t+5 / mean |ret| t-20..t-1); flip_10 = filtered regime differs from day-t regime at any of t+1..t+10; statements split at the median |tone_surprise|; placebo band = 2.5-97.5 pct of the mean over 1000 random non-statement samples of the same size.

| pair | n | vol_change high | vol_change low | placebo band (vol) | flip_10 high | flip_10 low | placebo band (flip) | Spearman(|surprise|, vol_change) | Spearman(|surprise|, flip_10) |
|---|---|---|---|---|---|---|---|---|---|
| EURUSD | 180 | +0.171 | +0.104 | [-0.189, -0.013] | 0.29 | 0.50 | [0.24, 0.44] | +0.075 | -0.158 |
| USDCHF | 180 | +0.048 | +0.079 | [-0.190, -0.000] | 0.14 | 0.21 | [0.09, 0.23] | -0.067 | -0.120 |

Does the SURPRISE matter beyond 'a statement happened'? High-minus-low difference with a 1000-shuffle permutation band (labels reshuffled among the statements):

| pair | vol_change high−low | permutation band | flip_10 high−low | permutation band |
|---|---|---|---|---|
| EURUSD | +0.067 | [-0.124, +0.109] | -0.21 | [-0.14, +0.14] |
| USDCHF | -0.032 | [-0.139, +0.137] | -0.07 | [-0.11, +0.11] |

Per bank (all statements of that bank, both pairs):

| pair | bank | n | vol_change | flip_10 |
|---|---|---|---|---|
| EURUSD | FOMC | 54 | +0.263 | 0.43 |
| EURUSD | ECB | 52 | +0.075 | 0.35 |
| EURUSD | SNB | 25 | +0.054 | 0.44 |
| EURUSD | BOE | 49 | +0.107 | 0.39 |
| USDCHF | FOMC | 54 | +0.195 | 0.22 |
| USDCHF | ECB | 52 | -0.006 | 0.13 |
| USDCHF | SNB | 25 | -0.038 | 0.16 |
| USDCHF | BOE | 49 | +0.044 | 0.18 |

## Honest reading

* **EURUSD** (n = 180): after ANY statement the next five days are more volatile than random days (all-statement vol_change +0.137 vs placebo mean -0.100, band [-0.189, -0.013]) — that is the calendar. The SURPRISE split adds +0.067 (high − low), which is INSIDE its permutation band [-0.124, +0.109]; the ten-day flip-rate difference is -0.21 (OUTSIDE its band). High-surprise vol_change +0.171 is outside the random-day band; its flip rate 29% is inside. Spearman(|surprise|, vol_change) = +0.07.
* **USDCHF** (n = 180): after ANY statement the next five days are more volatile than random days (all-statement vol_change +0.063 vs placebo mean -0.095, band [-0.190, -0.000]) — that is the calendar. The SURPRISE split adds -0.032 (high − low), which is INSIDE its permutation band [-0.139, +0.137]; the ten-day flip-rate difference is -0.07 (INSIDE its band). High-surprise vol_change +0.048 is outside the random-day band; its flip rate 14% is inside. Spearman(|surprise|, vol_change) = -0.07.

* Four high−low differences are tested (2 pairs × vol/flip); one outside its band at the 5% level is what chance alone produces, and a difference in the counter-intuitive sense (FEWER flips after high surprise) is read as noise — most likely the tone ratio saturating at ±1 on short statements, which inflates |surprise| for the briefest (often calm-period) releases. We do not claim an effect from it.
* Verdict for the Stage-2 gate: a credible live effect means the high−low SURPRISE difference outside its permutation band, on LIVE (post-2026-08-17) statements. The historical lexicon result above is the benchmark the live record will be held to — it is not itself evidence for opening the gate.
* The corpus is small (a few dozen statements per bank since 2020), the tone ratio saturates at ±1 on very short statements (two or three hits), and the lexicon is a deliberately simple frozen word list, so single-pair, single-split numbers like these are noisy; a point estimate inside a band is 'no detectable effect', not 'no effect'.
* Statement days cluster with other scheduled macro events, so some of any excess volatility is the calendar, not the words; the phase-23 `days_to_*` features carry that part.
* Nothing here is a trading signal. The lexicon features may join the CHALLENGER forecaster only (volatility / regime targets), and Stage 2 (LLM) stays gated — see docs/stage2-decision.md.

Figures: `reports/cb_event_study_vol.png`, `reports/cb_event_study_flips.png`.

*Educational tool. Not investment advice.*
