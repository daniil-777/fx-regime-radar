---
description: Phase 01 — price data loader with ECB cross-validation (v0.2.0)
---

Read CLAUDE.md. Build the data layer in `src/fxradar/data.py`.

## Task
Download daily FX prices for EURUSD, USDCHF, GBPUSD since 2005-01-01, validate
them against an independent official source, and write `data/prices.parquet`
matching the data contract exactly.

## Requirements
1. `download_prices(pairs, start) -> DataFrame`: use yfinance (`EURUSD=X`,
   `CHF=X`, `GBPUSD=X`), 3 retries with backoff, return tidy long format
   (date, pair, open, high, low, close), pair names normalized to EURUSD etc.
   Keep trading days only; never forward-fill prices across missing days.
2. `validate_against_ecb(df) -> dict`: fetch ECB reference rates from the free
   frankfurter.app API for EURUSD and USDCHF over the last 3 years, align on
   date, and report count compared, mean and max absolute percent deviation of
   closes. Log a WARNING above 0.5% mean deviation; raise above 2%.
   (Reference rates are daily fixings, so small deviations are expected —
   put that sentence in the docstring.)
3. `save_prices(df)` writes `data/prices.parquet`. Add a `__main__` CLI so
   `python -m fxradar.data` runs download → validate → save and prints a
   summary: rows per pair, date range, validation stats.
4. Tests in `tests/test_data.py` (use a small saved fixture parquet, no network
   in tests): schema and dtypes match the contract; dates strictly increasing
   per pair; all prices positive; plausible ranges (EURUSD between 0.7 and 2.0).
5. Save a quick sanity plot of the three close series to
   `reports/prices_overview.png` from the CLI run.

## Do not
No indicators or features here. No forward-filling. No network calls inside
pytest. Do not silently drop pairs — fail loudly if a download is empty.

## Verify
- `python -m fxradar.data` completes; show me the printed summary and confirm
  `data/prices.parquet` and the png exist.
- `make test` green. Load the parquet in a one-liner and show head and tail.
- Update CHANGELOG, commit `phase-01: data loader`, tag `v0.2.0`.

## Teach me
Explain: why we validate against a second source, why long/tidy format, and why
holidays must stay missing rather than filled. Then two interview questions
about data quality in finance; critique my answers.
