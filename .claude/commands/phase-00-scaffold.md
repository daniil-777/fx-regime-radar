---
description: Phase 00 — scaffold the repository, tooling, and empty app shell (v0.1.0)
---

Read CLAUDE.md fully before doing anything. Then scaffold the project.

## Task
Create the complete repository skeleton exactly as specified in CLAUDE.md's
"Repository layout", with working tooling, so that tests and the app shell run
before any real logic exists.

## Requirements
1. Create every directory and empty module from the layout, each module with a
   one-line docstring stating its future purpose. Add `src/fxradar/__init__.py`
   with `__version__ = "0.1.0"`.
2. `requirements.txt`: pandas, numpy, pyarrow, yfinance, requests, hmmlearn,
   scikit-learn, xgboost, shap, plotly, streamlit, anthropic, joblib, pytest,
   black, ruff — pinned to current major versions.
3. `Makefile` targets: `setup` (venv + pip install), `test` (pytest -q),
   `lint` (ruff + black --check), `fmt`, `run` (streamlit run app/app.py),
   `pipeline` (python pipelines/run_daily.py).
4. `.gitignore`: venv, __pycache__, .streamlit/secrets.toml, .DS_Store,
   *.egg-info. Note: data/ and models/ are COMMITTED by design (see CLAUDE.md).
5. `tests/test_smoke.py`: imports every fxradar module and asserts the version.
6. `app/app.py`: minimal placeholder page titled "FX Regime Radar" with the
   disclaimer line from CLAUDE.md rule 7 in the footer.
7. `.streamlit/config.toml`: dark theme using the design-system colors.
8. `CHANGELOG.md` with a v0.1.0 entry. `README.md` with a 5-line project stub.
9. Make the package importable (pyproject.toml with src layout, or setup.cfg —
   your choice, keep it minimal). Configure ruff + black in the same file.
10. `git init`, first commit `phase-00: scaffold`, tag `v0.1.0`.

## Do not
Do not add any data downloads, model code, or extra dependencies. Do not create
notebooks. Do not touch secrets.

## Verify (run these; all must pass, show me the output)
- `make setup && make test && make lint`
- `make run` starts and the page renders with the disclaimer (then stop it).
- `git log --oneline` shows the tagged commit.

## Teach me
Explain in plain language: why the src layout, why we commit data/ artifacts in
this specific project, and what the Makefile buys us. Then ask me two short
interview-style questions about project structure and critique my answers.
