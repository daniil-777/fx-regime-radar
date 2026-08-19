# Storm replays — selection rule and method

Three named crises replayed day by day through the radar's real scoring path, published exactly as
the replay computed them. Reports: `reports/storms/`. Artifact: `data/storm_replays.json`. App page:
**Storms**. Engine: `src/fxradar/replay.py`.

> **Causal reconstruction — not the live record.** The live record is the hash-chained ledger
> (`data/ledger.parquet`, started on the date in `data/live_record.json`; see the Proof page).
> A replay shows what the radar *would have* shown; the ledger shows what it *did* show, recorded
> before the outcome existed. The two are never blended.

## Selection rule

**Windows are the three named crises every Swiss treasurer remembers, fixed in advance; no window
was chosen after seeing the results.** The list is closed — adding a window later would be
cherry-picking and is refused by `tests/test_replay.py::test_windows_fixed_in_advance`.

| key | window | pair the report tells | reference event |
|---|---|---|---|
| `covid_2020` | 2020-02-03 → 2020-04-30 | EURUSD | WHO pandemic declaration, 11 March 2020 |
| `credit_suisse_2023` | 2023-03-01 → 2023-03-31 | USDCHF | UBS takeover announced Sunday 19 March 2023 |
| `snb_2015` | 2015-01-05 → 2015-01-30 | USDCHF | EUR/CHF floor removed 15 January 2015 (unscheduled) |

All three pairs are replayed for every window (the json holds all rows); each report tells one pair
and lists the other two in one line each.

## Method

For every trading day *t* in a window:

1. **Truncate** the raw prices at *t*: `prices[prices.date <= t]` — nothing after *t* exists.
   The whole history before *t* is kept (2005 →), so the result is bit-identical to the artifact
   (a trailing warm-up window agrees only to ~1e-13: pandas' online rolling std and the HMM's
   forward-filter prior carry float state — drift, not look-ahead).
2. **Score** with the SAME functions and the SAME saved models the daily pipeline uses, never a refit:
   `features.build_features` → `hmm_model.score_all` (filtered, forward algorithm) →
   `forecaster.build_matrix` + `forecaster.score` (XGBoost + Platt, row-wise) →
   `siren.reconstruction_errors` + `siren.percentile_of` against the frozen calm-train reference
   (→ `conformal.apply` and `bocpd.score_all` when those modules and their fitted params exist;
   their columns are NaN otherwise).
3. **Keep day *t* only** and move on.

Because every feature and the forward filter are causal, the replayed row at *t* must equal the row
the full-history artifact holds for *t*. Tests assert that to 1e-9 against `data/regimes.parquet`
(`test_replay_equals_full_history`) and against the live ledger (`test_replay_equals_ledger`),
plus truncation invariance of the engine itself (`test_replay_truncation_invariance`). If any of
these ever failed, something in the pipeline would be looking ahead.

Cost: roughly 4–5 s per replayed day (the HMM forward loop and BOCPD run over the full history);
the three windows take ~8 minutes with `make storms` / `python -m fxradar.replay`.

## What a report contains

* the banner above + the selection rule;
* **the numbers**: first alarm (change risk ≥ the forecaster's frozen validation threshold, 0.22),
  first crisis day, alarm → flip lag in trading days (negative when the flip came first — printed
  as such), peak siren day and percentile, crisis-day count and longest run;
* a png (close with replayed regime bands, change risk vs threshold, siren percentile);
* **buildup / alarm timing / aftermath** paragraphs — templates filled with the numbers, no
  hindsight adjectives, no direction words (a regex test guards the templates);
* the day-by-day table (date, regime, confidence, change risk, siren pct, conformal band and
  consensus where present);
* report C (SNB) carries the sidebar *"What a pegged EUR/CHF looked like"*: a vol-based radar is
  blind to a pegged cross, the floor removal was unscheduled, and the siren's 100 on 15 January is
  detection of an unprecedented move, not a prediction. What the radar did **not** do is stated
  plainly with the pre-event change-risk numbers.

## Auto post-mortems

`replay.stage(ctx)` runs in the daily pipeline after the narrator. When the newest row of any pair
is `crisis` and the previous row was not (a live entry into crisis), it drafts
`reports/postmortems/<date>_<pair>.md` — the last 30 live rows in the same template — headed
**DRAFT — for human review**. Nothing is published from there without a person reading it; the
live record stays the ledger.

## Honesty checklist (what a dishonest report would do, and what stops it)

* pick the window after seeing the numbers → the closed `WINDOWS` dict + test;
* smooth the HMM (use future rows) to make the flip look earlier → `test_replay_equals_full_history`
  would still pass only if the artifact itself were smoothed, which `tests/test_hmm.py`'s
  truncation test forbids; the replay's own per-day truncation makes smoothing impossible by
  construction;
* refit a model on the storm → the replay loads bundles only; there is no fit call in `replay.py`;
* soften "no warning" into prose → the lag is printed as a signed number and the template says
  "did not warn ahead" when it is negative.

_Educational tool. Not investment advice._
