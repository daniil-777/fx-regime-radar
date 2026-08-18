# FX Regime Radar — developer commands. Every target uses the project venv explicitly,
# so nothing depends on which python happens to be on your PATH.
PY      ?= python3.11
VENV    := .venv
BIN     := $(VENV)/bin
PYTHON  := $(BIN)/python

.PHONY: setup test lint fmt run pipeline refit

setup:            ## create venv and install everything (idempotent)
	test -d $(VENV) || $(PY) -m venv $(VENV)
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -r requirements.txt
	$(PYTHON) -m pip install -e .

test:             ## run the test suite quietly
	$(PYTHON) -m pytest -q

lint:             ## static checks: ruff (lint) + black (format check)
	$(BIN)/ruff check .
	$(BIN)/black --check .

fmt:              ## auto-format and auto-fix imports
	$(BIN)/ruff check --fix .
	$(BIN)/black .

run:              ## start the Streamlit app (reads artifacts only)
	$(BIN)/streamlit run app/app.py

pipeline:         ## run the daily pipeline (the only place heavy compute happens)
	$(PYTHON) pipelines/run_daily.py

# Deliberate model refit (monthly cadence). Example:
#   make refit TRAIN_END=2024-12-31 HMM_VERSION=0.4.1
# Refits invalidate the frozen out-of-sample evaluation, so the validation report is rebuilt.
TRAIN_END   ?= 2016-12-31
HMM_VERSION ?= 0.4.0
refit:            ## refit HMM on an expanded window, bump model version, re-validate, re-score
	$(PYTHON) -m fxradar.hmm_model --refit --train-end $(TRAIN_END) --version $(HMM_VERSION) --stability
	$(PYTHON) -m fxradar.validate
	$(PYTHON) pipelines/run_daily.py
	$(PYTHON) -m fxradar.export   # last act of a refit: pack the bundle that crosses the wall
