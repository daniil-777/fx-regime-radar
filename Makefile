# FX Regime Radar — developer commands. Every target uses the project venv explicitly,
# so nothing depends on which python happens to be on your PATH.
PY      ?= python3.11
VENV    := .venv
BIN     := $(VENV)/bin
PYTHON  := $(BIN)/python

.PHONY: setup test lint fmt run pipeline refit train-universe set-repo ledger

setup:            ## create venv and install everything (idempotent)
	test -d $(VENV) || $(PY) -m venv $(VENV)
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -r requirements.txt
	$(PYTHON) -m pip install -e .

test:             ## run the test suite quietly
	$(PYTHON) -m pytest -q

ledger:           ## append today's forecasts to the live forward-test ledger from the committed artifacts
	$(PYTHON) -m fxradar.ledger --record

# After forking: point the README badges (ci / daily / rust / live record) at your repository.
#   make set-repo REPO=you/fx-regime-radar
set-repo:         ## replace the OWNER/REPO badge placeholder in README.md
	@test -n "$(REPO)" || (echo "usage: make set-repo REPO=owner/name" && exit 1)
	sed -i.bak "s#OWNER/REPO#$(REPO)#g" README.md && rm -f README.md.bak

lint:             ## static checks: ruff (lint) + black (format check)
	$(BIN)/ruff check .
	$(BIN)/black --check .

fmt:              ## auto-format and auto-fix imports
	$(BIN)/ruff check --fix .
	$(BIN)/black .

run:              ## start the Streamlit app (reads artifacts only)
	$(BIN)/streamlit run app/app.py

# UNIVERSE=fx (default) or crypto — selects instruments, splits, thresholds and artifact folders
UNIVERSE ?= fx
pipeline:         ## run the daily pipeline for a universe (the only place heavy compute happens)
	FXRADAR_UNIVERSE=$(UNIVERSE) $(PYTHON) pipelines/run_daily.py

train-universe:   ## build a new universe from scratch: data → features → HMM → validate → forecaster → siren → strategies → stress
	FXRADAR_UNIVERSE=$(UNIVERSE) $(PYTHON) -m fxradar.data
	FXRADAR_UNIVERSE=$(UNIVERSE) $(PYTHON) -m fxradar.features
	FXRADAR_UNIVERSE=$(UNIVERSE) $(PYTHON) -m fxradar.hmm_model --refit
	FXRADAR_UNIVERSE=$(UNIVERSE) $(PYTHON) -m fxradar.validate
	FXRADAR_UNIVERSE=$(UNIVERSE) $(PYTHON) -m fxradar.forecaster --train
	FXRADAR_UNIVERSE=$(UNIVERSE) $(PYTHON) -m fxradar.siren --train
	FXRADAR_UNIVERSE=$(UNIVERSE) $(PYTHON) pipelines/run_daily.py
	FXRADAR_UNIVERSE=$(UNIVERSE) $(PYTHON) -m fxradar.strategies
	FXRADAR_UNIVERSE=$(UNIVERSE) $(PYTHON) -m fxradar.stress

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
