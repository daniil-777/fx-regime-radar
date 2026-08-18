# Changelog

All notable changes to FX Regime Radar. Versions follow the phase plan in USAGE.md.

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
