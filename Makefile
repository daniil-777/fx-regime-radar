# FX Regime Radar — developer commands. Every target uses the project venv explicitly,
# so nothing depends on which python happens to be on your PATH.
PY      ?= python3.11
VENV    := .venv
BIN     := $(VENV)/bin
PYTHON  := $(BIN)/python

.PHONY: setup test lint fmt run pipeline refit train-universe set-repo ledger viz3d gif docker docker-down rust-keys features-ext challenger event-study cb-fetch cb-features cb-gate treasury weekly metrics storms verify-ledger

setup:            ## create venv and install everything (idempotent)
	test -d $(VENV) || $(PY) -m venv $(VENV)
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -r requirements.txt
	$(PYTHON) -m pip install -e .

viz3d:            ## fit + persist the landscape embeddings (train rows only) for UNIVERSE — display layer
	FXRADAR_UNIVERSE=$(UNIVERSE) $(PYTHON) -m fxradar.viz3d --fit

gif:              ## render assets/tetrahedron.gif (README header) — needs dev deps: pip install -r requirements-dev.txt
	$(PYTHON) -m pip install -q -r requirements-dev.txt
	$(PYTHON) scripts/make_gif.py

docker:           ## production stack locally: app image + Caddy on http://localhost (needs Docker)
	cd deploy && ( test -f .env || cp .env.example .env ) && docker compose up -d --build

docker-down:      ## stop the production stack
	cd deploy && docker compose down

test:             ## run the test suite quietly
	$(PYTHON) -m pytest -q

treasury:         ## rebuild data/treasury_risk.json (regime-conditional VaR/ES + traffic light) from committed artifacts
	$(PYTHON) -m fxradar.treasury

weekly:           ## write this Monday's FX weather report (md + e-mail HTML + RSS) from committed artifacts
	$(PYTHON) -m fxradar.weekly

metrics:          ## refresh data/metrics.json (ledger days, subscribers, keys, partners, MRR — honest zeros)
	$(PYTHON) -m fxradar.metrics_page

storms:           ## replay the three flagship storms through the real scoring path (≈8 min) → data/storm_replays.json + reports/storms/
	$(PYTHON) -m fxradar.replay

rust-keys:        ## issue an API key for the Rust service: make rust-keys ARGS="--label acme --tier pro"
	cd rust/fxradar-serve && cargo run --release --bin keys -- --db ../../data/keys.db issue $(ARGS)

features-ext:     ## refresh context caches + rebuild data/features_ext.parquet (calendar, cross-asset, EPU, COT, Yang-Zhang)
	$(PYTHON) -m fxradar.features_ext --refresh

challenger:       ## (re)train the challenger forecaster on features + features_ext; frozen scoreboard in reports/challenger_eval.md
	$(PYTHON) -m fxradar.challenger --train

event-study:      ## placebo-tested event study figures -> reports/event_study_*.png
	$(PYTHON) scripts/event_study.py

cb-fetch:         ## fetch official central-bank statements into data/cb/ (idempotent, polite)
	$(PYTHON) -m fxradar.cb_text --backfill --since 2020

cb-features:      ## lexicon-score data/cb/ -> data/cb_features.parquet + event study report
	$(PYTHON) -m fxradar.cb_features
	$(PYTHON) scripts/cb_event_study.py

cb-gate:          ## print the Stage-2 gate with the real live counts (never scores when closed)
	$(PYTHON) -m fxradar.cb_llm

verify-ledger:    ## public proof: recompute the ledger hash chain with the standard library only
	python3 scripts/verify_ledger.py

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
