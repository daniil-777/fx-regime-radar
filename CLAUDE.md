# FX Regime Radar — project constitution

You are building FX Regime Radar: a production-style "weather station" for currency
markets. An HMM nowcasts the current market regime for EUR/USD, USD/CHF and GBP/USD;
an XGBoost model forecasts 5-day regime-change risk with SHAP explanations; an MLP
autoencoder flags anomalous days; a small LLM call narrates the computed numbers in
plain English. Purpose: a hiring-grade portfolio project for quant/fintech roles.
The developer is a motivated beginner — code must be simple, explained, and defensible
in interviews.

## Golden rules (non-negotiable, override everything else)

1. NO FUTURE DATA IN FEATURES. Every feature at day t uses only data up to day t.
   HMM-derived features must be FILTERED (causal, forward algorithm), never smoothed
   posteriors. Labels may look forward; features may not.
2. TIME-ORDERED SPLITS ONLY. Train ≤ 2016-12-31, validation 2017–2018, test 2019+.
   Apply a 5-trading-day embargo gap at every split boundary. The test set is scored
   once, at the end of a phase, and the number is frozen.
3. NEVER REPORT PLAIN ACCURACY for the forecaster. Report PR-AUC, precision/recall
   on transition events, and Brier score with a calibration plot. Always compare
   against the persistence base rate, a logistic regression, and a one-feature rule.
4. THE LLM NARRATES COMPUTED NUMBERS ONLY. It never analyzes markets from its own
   knowledge, never predicts prices, never gives advice. Structured JSON in, short
   text out. Deterministic template fallback if the API is unavailable.
5. NO PRICE-DIRECTION PREDICTION anywhere in this project. We model regimes,
   change risk, and anomalies — not returns.
6. EVERY FINANCIAL CALCULATION HAS A PYTEST TEST, including at least one
   "truncation invariance" leakage test per feature module: computing on a
   truncated series must reproduce the overlapping rows exactly.
7. USER-FACING SURFACES carry: "Educational tool. Not investment advice." (app
   footer + sidebar + README).
8. PIPELINE WRITES, APP READS. All heavy compute happens in `pipelines/run_daily.py`,
   which writes small artifacts. The Streamlit app only reads artifacts and must
   load in ~1 second. Never train or download data inside the app.
9. NO SECRETS IN CODE OR GIT. `ANTHROPIC_API_KEY` lives in `.streamlit/secrets.toml`
   (gitignored) locally and in repo/deployment secrets in CI. Everything must run
   without a key (template fallback) so tests and contributors never need one.
10. FINISH EVERY PHASE by running the verify block, updating CHANGELOG.md, and
    committing with `phase-NN: <summary>` plus the phase's version tag.
11. THE WALL (phases 11+). Python is the research side only: training,
    validation, narration, export. The production serving path is Rust and
    imports nothing from Python at runtime. The versioned model bundle
    (ONNX + json params + feature spec + golden vectors + hashed manifest)
    is the ONLY artifact that crosses. Pickle never crosses the wall. The
    Rust service replays all golden vectors at startup and refuses to serve
    on any mismatch (features 1e-8, model outputs 1e-6).
12. THE STRATEGY LAYER (phases 14+). Signals are inputs; net-of-costs P&L is
    the product. The lag law is absolute: a signal formed at close t earns
    returns from t+1, enforced inside the backtest engine and proven by the
    foresight test. Costs scale with volatility and are charged on turnover.
    Gross numbers never appear without net beside them; the headline is
    always out-of-sample net. Strategy parameters are frozen after
    validation; stress results are reported even when ugly, and nothing in
    this repo claims to be a live trading system.
13. GAMIFICATION ETHICS (phases 17+). Gamify learning and calibration only —
    never trading actions, frequency, position size, or risk-taking. No
    urgency mechanics, no confetti, no loss shaming, no dark patterns. The
    model's probability is revealed only after the user locks their own
    call. All motion respects prefers-reduced-motion; reading surfaces stay
    still. Game copy never references money. Storm-gallery content is
    human-verified before it ships.

## Architecture

GitHub Actions (cron, weekdays 06:00 UTC)
  → pipelines/run_daily.py
      data → features → HMM score → forecaster score → siren score → narrator
  → writes data/prices.parquet, data/features.parquet, data/regimes.parquet,
    data/report.json  (committed to the repo)
  → app/ (Streamlit) reads artifacts only.

## Repository layout

```
fx-regime-radar/
├── CLAUDE.md
├── README.md            CHANGELOG.md          Makefile
├── requirements.txt     .gitignore
├── .streamlit/config.toml        (.streamlit/secrets.toml gitignored)
├── .github/workflows/daily.yml
├── src/fxradar/
│   ├── config.py    data.py      features.py
│   ├── hmm_model.py forecaster.py siren.py    narrate.py
├── pipelines/run_daily.py
├── app/app.py  app/pages/1_Methodology.py  app/ui.py
├── models/          (saved model files, versioned names)
├── data/            (parquet + json artifacts, committed)
├── reports/         (validation markdown + png plots)
├── docs/            (screenshots, model cards, interview notes)
├── rust/fxradar-serve/   (phases 12+: engine, selftest, axum service)
│   (src/fxradar/ also gains backtest.py, strategies.py, stress.py at 14+)
├── models/bundle_v*/     (phase 11+: the only artifact crossing the wall)
└── tests/
```

## Data contracts (column names are law)

- prices.parquet: date, pair, open, high, low, close — daily, long format, 2005→today,
  pairs: EURUSD, USDCHF, GBPUSD.
- features.parquet: date, pair, ret_1d, vol_20, vol_60, vol_ratio, mom_20, rng_hl,
  corr_20, ret_5d_abs (base) + hmm_entropy, days_in_regime, vol_trend (post-HMM).
- regimes.parquet: date, pair, regime, regime_prob, hmm_entropy, days_in_regime,
  change_risk_5d, top_drivers, anomaly_score, anomaly_pct, model_version.
- report.json: {pair: {text, generated_at, source: "llm"|"template"}}.
- backtests.parquet: date, strategy, pair, pos, ret_gross, ret_net, cost_bps.

## Design system (the app must not look like default Streamlit)

- Dark theme. Background #0B0F17, surface #131A26, border #232D3F,
  text #E7ECF4, muted #8A94A6.
- Regime colors: calm #34D399, trend #60A5FA, chop #FBBF24, crisis #F87171.
  Use these everywhere: pills, timeline bands, gauges.
- Fonts: Inter for UI, JetBrains Mono for numbers (Google Fonts import in CSS).
- Hide Streamlit chrome (menu, footer, deploy button) via CSS. Card-based layout:
  rounded 12px, 1px border, generous padding. One accent per element, no rainbow.
- Plotly: single custom dark template defined once in app/ui.py and reused.

## Coding standards

Python 3.11+. Type hints and short docstrings on public functions. Small modules,
no notebooks in the final repo. Format with black, lint with ruff (both configured
in pyproject or setup.cfg). Pin top-level dependencies in requirements.txt.
Functions take dataframes in, return dataframes out; I/O lives at the edges.
Prefer boring, readable code over clever code — the developer must be able to
explain every line in an interview.

## Definition of done, every phase

Tests green (`make test`) · verify block of the phase passes · CHANGELOG updated ·
committed and tagged · finish by teaching: explain the phase's key concepts to the
developer in plain language, then ask them two interview-style questions and give
honest feedback on their answers.
