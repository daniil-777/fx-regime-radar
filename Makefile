# FX Regime Radar — developer commands. Every target uses the project venv explicitly,
# so nothing depends on which python happens to be on your PATH.
PY      ?= python3.11
VENV    := .venv
BIN     := $(VENV)/bin
PYTHON  := $(BIN)/python

.PHONY: setup test lint fmt run pipeline

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
