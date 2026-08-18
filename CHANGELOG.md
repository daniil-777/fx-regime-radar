# Changelog

All notable changes to FX Regime Radar. Versions follow the phase plan in USAGE.md.

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
