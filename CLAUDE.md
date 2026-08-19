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

## Design system (the app must not look like default Streamlit) — phase 31, trust-first

SINGLE SOURCE OF TRUTH: `design/tokens.json`. `fxradar.tokens` loads it; `app/ui.py`, the Plotly
template, the matplotlib report figures, the orb presets, the e-mail report and `widget.js` derive
from it; `scripts/gen_tokens.py` (`make tokens`) regenerates `.streamlit/config.toml`,
`design/tokens.css` and the Rust static tokens. `make lint-ui` (in CI) FAILS on any hex literal in
app/, src/, scripts/ or pipelines/ — every future phase obeys without being told. Target:
`design/design-target-mockup.html` — match it, don't reinterpret it.

- Surfaces: nimbus #0E1420 (app) · front #151D2E (cards, sidebar) · line rgba(255,255,255,.08)
  (hex twin #1F2838 for SVG/Plotly strokes) · grid rgba(255,255,255,.06).
- Text: #E8ECF4 primary · #9AA6B8 secondary · #7B89A1 dim (mockup's #5C6980 lifted for 4.5:1 —
  tone adjusted, meaning unchanged). Contrast ≥ 4.5:1 for every text/surface pair (tested).
- Regime colours are DATA AND STATUS ONLY, never decoration: calm #3ECF8E, trend #4DA3FF,
  chop #F5B942, crisis #FF5C5C. Regime is never colour-only: word + dot. Link/action accent
  beacon #7FD1C9. Light variant (e-mail report only) in tokens.json.
- Type at the one Google Fonts import: Space Grotesk (display — regime words, page titles only),
  IBM Plex Sans (UI/body), IBM Plex Mono for EVERY number, hash and ledger value with tabular
  figures ('tnum'); numbers right-aligned in tables. No third family, no weight above 500.
- Signature structures (in app/ui.py, used on every surface): the CONDITION BANNER (eyebrow with
  pair + data-through, the regime word huge in its colour, one metrics line — change risk ± band,
  siren — the quiet 90-day risk trace with shaded band, the three-dot consensus) and the TRUST STRIP
  (forward-test day count, live Brier vs frozen, coverage vs target, chain head + check, "verify
  independently"), never below the fold. If anything competes with the banner, quiet the element.
- Motion budget: the orb is the ONE ambient element; the only other motion is the live dot's slow
  pulse; both honour prefers-reduced-motion. No third animation, ever. No gradients, glassmorphism,
  glow or shadow soup. No emoji as UI. Cards: 12 px radius, 1 px hairline, generous padding.
- Plotly: one template (`ui.PLOTLY_TEMPLATE`), transparent background, 6 %-white gridlines, muted
  mono axes; regime context via `ui.regime_bands` ONLY — a faint 10 % full-height tint plus a thin
  saturated baseline ribbon (the price line stays the loudest element; the ribbon carries the state).
  Semantic colours only; never green/red for price direction (we have no direction).
- Density: numbers in well-set tables beat decoration; paragraphs inside cards are clamped
  (`fx-clamp`) with the full text one click away (progressive disclosure); the market tabs sit in
  the header on every width (synced with the sidebar); inputs are defined fields (nimbus + hairline).
- IA: Radar = Overview · Pairs · Treasury · Storms · Proof; Analysis = Advisor · Regime space ·
  Probability space · Strategy lab · Arcade; About = Methodology · Weekly report · Metrics. Every
  widget answers "what does the user decide with this?" Empty/loading/error states use `ui.state`:
  say what happened and what to do, never apologise, never vague. Responsive to 360 px; visible
  keyboard focus.

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
