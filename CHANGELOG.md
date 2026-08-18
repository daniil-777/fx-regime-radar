# Changelog

All notable changes to FX Regime Radar. Versions follow the phase plan in USAGE.md.

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
