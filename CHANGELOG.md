# Changelog

All notable changes to FX Regime Radar. Versions follow the phase plan in USAGE.md.

## v1.3.0 — phase-09: narrator (2026-08-18)

- `src/fxradar/narrate.py`: `build_stats(pair)` (numbers only: regime, regime_prob,
  days_in_regime, change_risk_5d, top_drivers, anomaly_pct, nearest-neighbour date, 5-day
  return); `narrate(stats)` via the Anthropic SDK — model `claude-haiku-4-5`, temperature 0.3,
  max_tokens 350, the verbatim guardrail system prompt, user content = the stats JSON only;
  key from env or Streamlit secrets; SDK retries (2, backoff); `template_narrate` writes the
  same three sentences deterministically; `narrate_with_fallback` never raises. Output
  `data/report.json` = {pair: {text, generated_at, source: "llm"|"template", stats}}.
- Pipeline stage `narrator` registered LAST; without a key the pipeline succeeds on the
  template path (verified). `daily.yml` passes the optional `ANTHROPIC_API_KEY` repository
  secret as an env var (empty → template).
- Dashboard: quote-style narration on every weather card with an AI/auto badge and timestamp;
  the app never calls the API (reads `report.json` only).
- README: how to add the key (GitHub secret, Streamlit secrets), cost estimate ≈ 5 ¢/month.
- Tests (`tests/test_narrate.py`, 5): template = exactly three sentences containing the regime
  and the risk figure (+ neighbour only when anomaly_pct > 90); missing key never raises; API
  failure falls back; mocked client receives the system prompt, model/temperature/max_tokens,
  and ONLY JSON-derived user content; build_stats types.

## v1.2.0 — phase-08: anomaly siren (2026-08-18)

- `src/fxradar/siren.py`: `MLPRegressor(hidden_layer_sizes=(8, 3, 8), max_iter=3000,
  early_stopping=True, random_state=42)` autoencoder on the 9 continuous features, scaler +
  model fit ONLY on train-period calm days with regime_prob > 0.7 (2 788 days, 2005-04-07 →
  2016-12-30), pooled across pairs, no pair one-hots (pair-agnostic by design — documented).
- Scoring: `anomaly_score` = mean squared reconstruction error; `anomaly_pct` = percentile
  against the calm-train distribution; per-feature squared errors + nearest historical
  neighbour (same pair, train period, ±10 days excluded) in `data/siren_detail.parquet`
  (for the phase-09 explainer). Scoring is truncation-invariant (tested).
- `reports/siren_validation.md` + `siren_anomaly_pct.png`: SNB 2015-01-15 is USDCHF's
  loudest day in history (rank 1, pct 100); Brexit 2016-06-24 rank 1 for GBPUSD; the
  2016-10-07 flash crash pct 100 (rank 139); March 2020: 68–82 % of days ≥ 98th pct. Honest
  reading: many merely-volatile days also scream; it detects, it does not predict.
- `models/siren_v1.2.0.joblib` (dict payload); manifest entry; pipeline stage `siren`
  registered — `regimes.parquet` now matches the full contract (model_version
  "hmm=0.4.0|fc=1.1.0|siren=1.2.0").
- Dashboard "Anomaly siren" section: SVG dial per pair (muted <90, amber 90–98, red >98),
  2-year sparkline, "Loudest days in history" table for the selected pair.
- Tests (`tests/test_siren.py`, 6): (8,3,8) architecture, scaler/model fit only on calm train
  days (date range + labels asserted), truncation invariance, percentile + outlier behaviour,
  neighbour exclusion window, saved-model SNB check.

## v1.1.0 — phase-07: forecaster (2026-08-18)

- `src/fxradar/forecaster.py`: pooled XGBoost classifier for "regime changes within the next
  5 trading days". Labels look forward; every feature is causal (matrix truncation-invariance
  test). Features exactly per spec (10 numeric incl. filtered HMM outputs + 3 regime one-hots
  + 2 pair one-hots). Time-ordered splits with a 5-day embargo on both sides of every boundary
  (tested). Fixed hyper-parameters, `scale_pos_weight` from train (4.88), early stopping on
  val (iteration 283). No grid search — deliberate.
- Probabilities are Platt-recalibrated on VALIDATION (a=0.95, b=−1.30): `scale_pos_weight`
  makes raw probabilities over-predict (raw Brier 0.128 vs 0.102 calibrated); both are shown.
  Threshold 0.22 chosen on val for recall ≥ 60 %.
- `reports/forecaster_eval.md` (+ `forecaster_calibration.png`, `forecaster_shap.png`), test
  set scored ONCE and frozen: PR-AUC 0.548 vs logistic 0.431, base rate 0.162, one-feature
  rule 0.143; precision 0.45 / recall 0.59 at the threshold; Brier 0.102 (logistic 0.116).
  Honest interpretation paragraph. Never accuracy.
- SHAP TreeExplainer: beeswarm png; per-day top-3 |SHAP| feature names → `top_drivers`.
- Model persisted as `models/forecaster_v1.1.0.json` (+ `.meta.json` with threshold,
  calibration, features, scoreboard); registered in `models/manifest.json`. Pipeline stage
  `forecaster` registered in `run_daily.py`; `regimes.parquet` now carries `change_risk_5d`
  and `top_drivers` (model_version "hmm=0.4.0|fc=1.1.0").
- Dashboard: "5-day change risk" gauge on every weather card (muted <20 %, amber 20–40 %,
  red >40 %) with the top drivers beneath.
- Tests (`tests/test_forecaster.py`, 8): label semantics, embargo gaps, matrix truncation
  invariance, exact feature list, threshold rule, Platt calibration recovers a known
  distortion, top-driver extraction, saved-model contract.

## v1.0.1 — phase-06: automation (2026-08-18)

- `pipelines/run_daily.py`: single orchestrator — stages `data → features → hmm → write`,
  registered with one line each (`register(name, fn)`) so phases 07–09 plug in. Models are
  LOADED (from `models/manifest.json`), never fitted. All compute runs in memory and every
  artifact is written in the final stage only, so any failure leaves `data/` untouched
  (verified: simulated failure → exit 1, files unchanged). Per-stage timings logged; full run
  ≈ 4 s locally. Idempotent: a rerun produces byte-identical parquet files. Writes
  `data/pipeline_status.json` (last run, data-through date, row counts, model versions, ECB
  check, timings) — the app shows "updated … UTC" from it. `FXRADAR_SIMULATE_FAILURE=<stage>`
  rehearses the failure path.
- `.github/workflows/daily.yml`: cron weekdays 06:00 UTC + `workflow_dispatch`; Python 3.11
  with pip cache; runs the pipeline; commits `data/` as `data: daily refresh [skip ci]`;
  `permissions: contents: write`; no secrets.
- `.github/workflows/refit.yml` (manual, inputs train_end + version) and `make refit
  TRAIN_END=… HMM_VERSION=…`: deliberate expanding-window refit that bumps the model version
  via `models/manifest.json`, regenerates the validation report and re-scores.
  `python -m fxradar.hmm_model` gained `--train-end/--version`.
- README: "Run locally" + "Deploy" (GitHub → Streamlit Community Cloud click-path, secrets
  note for phase 09, refit policy, failure honesty).
- Tests (`tests/test_pipeline.py`): success writes all artifacts + status; failure leaves the
  last good state and exits nonzero; simulated-failure env var; stage order.

## v1.0.0 — phase-05: dashboard v1 (2026-08-18) — first shippable

- `app/ui.py` owns the look: Google Fonts (Inter + JetBrains Mono), Streamlit chrome hidden,
  card class (#131A26 surface, 1px #232D3F border, 12px radius, 20px padding), regime pills
  in the four regime colours, one Plotly dark template (`fxradar_dark`) reused everywhere,
  helpers `regime_pill`, `card`, `confidence_bar`, `sparkline_svg`, `html_table`, `sidebar`,
  `footer`.
- `app/app.py`: header (wordmark, "market weather, updated daily", right-aligned "Data
  through …" from the artifact); hero row with one weather card per pair (pair, big regime
  pill, confidence bar, "day N of this regime", last close, inline-SVG 20-day sparkline);
  main panel with pair selector — Plotly close chart with merged regime bands (shapes), the
  out-of-sample divider at 2017-01-01 with annotation, 1y/3y/max range buttons; out-of-sample
  regime anatomy table (same definitions as the phase-04 report). Reads only
  `data/regimes.parquet` + `data/prices.parquet` (light pandas, no model imports).
- `st.cache_data` loaders keyed by file mtime; measured first paint ≈ 1.2 s cold, 0.1 s warm.
- `app/pages/1_Methodology.py`: pipeline, HMM + mood metaphor, filtered vs smoothed in two
  sentences, out-of-sample note, full Limitations. Disclaimer in sidebar + footer on every page.
- `docs/screenshots/dashboard_v1.png` (headless Chrome via `tools/screenshot.py`, main
  content crop). Sidebar holds only the pair selector and the disclaimer.
- Tests (`tests/test_app.py`): both pages render from artifacts without exceptions, carry the
  disclaimer in sidebar and footer, one Plotly figure, load-time budget.

## v0.5.0 — phase-04: hmm validation (2026-08-18)

- `src/fxradar/validate.py` + CLI `python -m fxradar.validate` → `reports/hmm_validation.md`
  with `regimes_timeline_{pair}.png` (close + regime bands, "out-of-sample →" divider at
  2017-01-01, design-system colours) and `regime_durations.png`.
- Sections: (1) regime anatomy train vs OOS (frequency, mean duration, ann. vol, mean daily
  return, worst drawdown inside each label); (2) 5-seed stability table with an honest
  paragraph (EURUSD mean 71 % < 80 % warning; trend/chop split is the fragile part);
  (3) naive baseline — "stressed" when vol_20 > trailing 250-day 80th percentile — agreement,
  Cohen's kappa and dated lead/lag episodes (the HMM does not systematically lead: 4 leads vs
  14 lags across matched episodes); (4) economic-meaning check — toy MA(50/200) rule's Sharpe
  per regime OOS: the "trend best / chop worst" claim FAILS and is reported as such;
  (5) plots; (6) Limitations (daily data, label noise, descriptive not predictive, frozen
  naming rule + SNB, single train window, Gaussian emissions).
- Tests (`tests/test_validate.py`, 7): max drawdown, Sharpe, run lengths, causal naive rule
  (truncation), episode/lead-lag logic, lagged MA rule (+ causality), table shapes.

## v0.4.0 — phase-03: hmm with filtered probabilities (2026-08-18)

- `src/fxradar/hmm_model.py`: one 4-state `GaussianHMM(covariance_type="full", n_iter=1000,
  random_state=42)` per pair on `[ret_1d, vol_20, mom_20]`, StandardScaler and model fit on
  the TRAIN window only (≤ 2016-12-31, `config.TRAIN_END`).
- `filtered_probs`: forward algorithm (per-frame Gaussian log-likelihoods + transition matrix,
  logsumexp-normalised each step) → P(state_t | obs ≤ t). Smoothed posteriors
  (`predict_proba`) are never used for any output. Tested against brute-force prefix
  recompute (60-row toy, atol 1e-8) and for truncation invariance; a companion test shows
  smoothed posteriors are NOT truncation-invariant.
- Frozen naming rule from train-period per-state stats: lowest mean vol_20 = calm, highest =
  crisis, of the middle two the larger |mean mom_20| = trend, other = chop. Persisted with the
  model. Honest note: for USDCHF the "crisis" state collapsed onto the 20 SNB-shock days
  (2015-01-16 → 2015-02-12; mean vol_20 65 %), so its 2008–11 stress carries the "chop" name
  — reported as-is for the phase-04 honesty report (clipping inputs was tried and made seed
  stability worse, so the spec-exact setup is kept).
- Outputs per pair/day: `regime`, `regime_prob`, `hmm_entropy` (nats, max ln 4),
  `days_in_regime`, `vol_trend` (sign of the 10-day change in vol_20), `model_version`
  ("hmm=0.4.0"). Written to `data/regimes.parquet` (the CLAUDE.md contract name — no
  `_base` variant; phases 07/08 enrich it in place) and the three post-HMM columns appended
  to `data/features.parquet`.
- Models: `models/hmm_{pair}_v0.4.0.joblib` (plain dict payload: model, scaler, mapping,
  train_end, version, features). CLI `python -m fxradar.hmm_model [--refit] [--stability]`
  loads saved models by default (never refits in the daily path).
- Results: mean regime_prob 0.96–0.98; transition-matrix diagonals 0.95–0.985 (sticky).
  5-seed label agreement vs seed 42: EURUSD 0.53–1.00 (mean 0.71, below the 80 % warning),
  GBPUSD 0.40–1.00 (mean 0.86), USDCHF 0.59–0.99 (mean 0.81) — EM local optima; discussed
  honestly in phase 04.
- Tests (`tests/test_hmm.py`, 10): filtering vs brute force, causality, frame log-likelihood
  vs hmmlearn, naming rule, run length, score outputs + truncation invariance, train-only
  scaler, bundle round trip, saved-model sanity (diag > 0.8, 4 states, permutation),
  contract of the artifacts.

## v0.3.0 — phase-02: feature engine (2026-08-18)

- `src/fxradar/features.py`: `build_features(prices)` computes the base contract features per
  pair — `ret_1d` (log return), `vol_20`/`vol_60` (rolling sample std × √252, ddof=1),
  `vol_ratio` (5-day vol / vol_60, the "storm front"), `mom_20`, `rng_hl` (10-day mean of
  (high−low)/close), `corr_20`, `ret_5d_abs`. Strictly causal; first 60 rows per pair dropped
  as warm-up; no scaling (models own their scalers).
- `corr_20` — deliberate, documented readings of the spec: (a) returns are put on one sign
  convention before correlating (USDCHF negated via `config.USD_BASE_PAIRS`, so every column
  is foreign-currency-vs-USD; the literal un-flipped mean gives medians −0.07/+0.04/−0.71
  because the +/− legs cancel, the flipped one gives 0.75/0.64/0.71 — a comparable
  "dollar-factor strength" across pairs); (b) each of the two correlations is computed on the
  dates both pairs traded and as-of aligned backward onto the pair's own dates (a hole in one
  pair only freezes that leg); (c) an undefined (zero-variance) window yields NaN, never a
  stale value.
- CLI `python -m fxradar.features`: prices.parquet → `data/features.parquet` (16 660 rows ×
  10, 2005-03-28 → 2026-08-17), prints shape, rows per pair, date range and NaN report (0).
- Tests (`tests/test_features.py`, 12): contract schema/dtypes, no post-warm-up NaNs, toy
  constant series, hand-computed vol_20/vol_60/vol_ratio/mom_20/ret_1d/rng_hl/ret_5d_abs,
  corr_20 mean-of-two + sign convention + hole + zero-variance semantics, TRUNCATION
  INVARIANCE (drop last 30 rows per pair; `assert_frame_equal(check_exact=True)`), one-pair
  truncation, shifting-start drift check. Verified on the full real history for k = 1, 5, 30.

## v0.2.0 — phase-01: data loader (2026-08-18)

- `src/fxradar/data.py`: `download_prices` (yfinance `EURUSD=X`, `CHF=X`, `GBPUSD=X`; 3 attempts
  with 2s/4s backoff; tidy long format `date, pair, open, high, low, close`; trading days only,
  never forward-filled; the in-progress current-day bar is excluded so reruns are reproducible;
  fails loudly on an empty pair).
- `validate_against_ecb`: frankfurter (ECB reference rates), last 3 years, EURUSD + USDCHF —
  count, mean and max absolute % deviation; WARNING above 0.5 % mean, error above 2 %.
  Measured: ~0.2 % mean deviation (fixings vs. Yahoo's start-of-day "close").
- Corrupted-print filters (`clean_prices`): reverting single-day bad ticks, absurd highs/lows
  (reciprocal-quoted prints) and out-of-bounds prices are DROPPED and logged with a reason,
  never repaired or filled. Currently 9 bars: 6× EURUSD 2008, USDCHF 2009-02-06,
  EURUSD + GBPUSD 2012-01-27. Real shocks (SNB 2015-01-15, Brexit) are untouched — tested.
- Documented Yahoo quirks in the module docstring: close ≈ start-of-day snapshot (so ~100
  rows/pair have close outside [low, high]); a 17-trading-day EURUSD source hole in Aug 2008.
- `python -m fxradar.data` CLI: download → clean → validate → save `data/prices.parquet` +
  `reports/prices_overview.png`; prints rows/date range/largest gap per pair, dropped bars,
  and ECB stats.
- `src/fxradar/config.py`: pairs, tickers, plausible price bounds, split dates + embargo,
  artifact paths, filter thresholds, `DISCLAIMER`.
- Tests (`tests/test_data.py`, 22 tests, no network): contract schema/dtypes, monotonic dates,
  positive + plausible OHLC, no weekends, tidy/no-fill/as-of cutoff, retry backoff, every
  filter rule (incl. "SNB survives" and row-order invariance), ECB stats/warn/raise (mocked),
  parquet round trip, summary + plot. Fixture: `tests/fixtures/prices_sample.parquet`
  (Oct 2014 – Dec 2015, 981 rows).
- `matplotlib` added to requirements (static pngs for `reports/`).

## v0.1.0 — phase-00: scaffold (2026-08-18)

- Repository skeleton matching CLAUDE.md "Repository layout": `src/fxradar` package
  (src layout, installable via `pyproject.toml`), `pipelines/`, `app/` (Streamlit shell),
  `models/`, `data/`, `reports/`, `docs/`, `tests/`.
- Tooling: `Makefile` (`setup`, `test`, `lint`, `fmt`, `run`, `pipeline`), pinned
  `requirements.txt`, ruff + black configured in `pyproject.toml`.
- `.streamlit/config.toml` dark theme with the design-system colours.
- `tests/test_smoke.py`: every module imports; version asserted.
- App shell renders the title and the disclaimer "Educational tool. Not investment advice."
- No data, no models, no secrets yet.
