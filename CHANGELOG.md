# Changelog

All notable changes to FX Regime Radar. Versions follow the phase plan in USAGE.md.

## v2.10.1 — always-on deploy: Docker + Oracle Always-Free (2026-08-18)

- `deploy/`: self-contained app image (`Dockerfile`, python:3.11-slim, non-root, healthcheck; every
  dependency has aarch64 wheels so it builds on Ampere A1), `docker-compose.yml` (app + Caddy with
  automatic HTTPS via `SITE_ADDRESS`, restart policies, artifacts bind-mounted from the git checkout),
  `Caddyfile`, `refresh.sh` (nightly `git pull` → restart on artifact-only changes, rebuild on code
  changes), `cloud-init.yaml` (Docker install, iptables 80/443, clone, first build, cron),
  `.env.example`; `.dockerignore`; `make docker` / `make docker-down`; CI workflow `docker image`
  (build + health check); guide `docs/DEPLOY_ORACLE.md`; README Deploy section updated.

## v2.10.0 — phase 19 (plan “24”): signature 3-D visuals, display layer only (2026-08-18)

- `src/fxradar/viz3d.py`: `simplex_coords` (exact `probs @ V`, order asserted, rows validated,
  uniform → origin), `filtered_probability_table`/`probability_frame` (replay of the frozen bundle's
  causal forward filter — never the smoother; the replay reproduces regimes.parquet exactly),
  `tetrahedron_figure` (6 edges, 4 labelled vertices in the regime palette, path coloured by time or
  siren, ringed today, hover with the four probabilities, all axes/planes hidden, `aspectmode="data"`),
  `fit_landscape_embedding` (scaler + PCA(3, random_state=42) FIT ON TRAIN ROWS ONLY, `train_end` and
  `n_fit_rows` stored; umap only if importable), `save/load_embedding` (joblib dict next to the models),
  `landscape_figure` (days by regime, 60-day brightening trail, ringed today), offline CLI `--fit`.
  Adaptation: the HMM consumes only 3 features (PCA(3) would be a rotation), so the landscape embeds
  the 8 causal base features with a train-only scaler.
- App: new page Radar → *Probability space* (`app/views/probability_space.py`): pair + colour-by
  segmented controls, explainer copy per figure, (A) above (B), universe-aware; every other panel
  unchanged and 2-D. Embeddings fit and committed for both universes (`models/landscape_*_pca.joblib`).
- `scripts/make_gif.py` + `make gif`: 72 frames × 5°, fixed elevation, 600 px, kaleido → imageio →
  `assets/tetrahedron.gif` (1.5 MB), embedded at the top of the README with the one-line caption;
  `make viz3d` fits the embeddings; `requirements-dev.txt` (kaleido, imageio — dev only).
- Tests `tests/test_viz3d.py` (13): exactness, validation, order guard, leakage (train-only fit,
  future-perturbation invariance), determinism + round trip, replay-vs-regime-table agreement.

## v2.9.1 — regime space: the feature space in 3-D (2026-08-18)

- New page `app/views/regime_space.py` (Radar → Regime space): the HMM's feature space rendered in WebGL,
  the only 3-D *chart* in the app (the orb is ambient) because the third axis is a real dimension,
  not a decorated time series.
  *State-space portrait*: one point per day at (realised vol log, 1-month momentum, selectable third
  axis), coloured by the day's filtered regime; regime centres; a 20–120-day trail to the ringed as-of
  marker; other pairs' same-day ghosts; ▶ replays the last year (~125 Plotly frames, every 2nd day,
  hover text computed once — the frame build is the page's cost, ≈ 0.45 s warm). *Regime landscape*:
  numpy 2-D histogram + binomial blur → density terrain over (vol, momentum), surface colour = dominant
  regime per cell in vol order (calm→crisis) so adjacent regimes get adjacent colour bands; empty cells
  are cut out (NaN) and inherit the nearest populated cell's colour index (else Plotly's per-face colour
  interpolation paints rainbow rims). *Geometry readout*: vol percentile, momentum, z-scored distance to
  each regime centre — labelled as a reading aid, distinct from the HMM probability.
- Reads `features.parquet` + `regimes.parquet` only, filtered to the as-of date (scenario explorer and
  deep links `?pair=&asof=` work); both universes; no new dependency (Plotly; scipy `distance_transform_edt`
  is already installed with scikit-learn).
- Router: `Regime space` under Radar; README section + repo tour; screenshots
  `docs/screenshots/regime_space{,_snb}.png`; AppTest `test_regime_space_page_renders_and_replays`.

## v2.8.1 — responsive pass: desktop, tablet, phone (2026-08-18)

- Regime orb fits its column: responsive square wrapper, canvas sized to the space it gets
  (`ResizeObserver`), `st.iframe(width="stretch")`; the orb column widened to `[1, 5]` and
  vertically centred with the chart title (it used to be clipped to a slice in a 1/8 column).
- One layout that adapts (no device sniffing): `@media` rules in `app/ui.py` — stacked header, 2×2
  KPI grid, tighter cards, scrollable tables (`.fx-table-wrap`), ≥ 40 px touch targets, orb hidden
  ≤ 640 px, three-across blocks two-across on tablets ≤ 1024 px, responsive sparklines.
- Mobile control bar (`ui.mobile_bar`): universe + market as `st.segmented_control`, hidden on
  desktop by CSS; kept equal to the sidebar selectboxes by `on_change` callbacks (widget values now
  live in session state — no `index=`, no Streamlit "default + session state" warning).
  `initial_sidebar_state="auto"` (collapsed on phones); the header stays (transparent, click-through)
  so the » open-sidebar button is reachable — it was hidden together with the toolbar before, which
  also stranded desktop users who collapsed the sidebar. Sidebar icon font no longer overridden
  (collapse arrow rendered as the ligature text `keyboard_double_arrow_left`).
- `tools/screenshot.py`: `--width/--height/--mobile/--eval` (device emulation, software WebGL, DOM
  introspection); AppTest `test_mobile_bar_mirrors_sidebar_controls_both_ways`.

## v2.9.0 — live forward-test ledger + real badges (2026-08-18)

- `src/fxradar/ledger.py`: append-only, SHA-256 hash-chained record of every forecast the pipeline
  publishes — one row per pair for the NEWEST date only (never backfilled: a forecast counts only
  if it was written down while its day was the latest observation, i.e. before the outcome could
  be known). Rows carry regime, change_risk_5d, anomaly_pct, model_version, recorded_at_utc,
  prev_hash → row_hash (chain over the forecast fields only). Five trading days later rows are
  *resolved* with `forecaster.build_labels`' definition verbatim and scored with `forecaster.metrics`
  (PR-AUC, precision/recall at the frozen threshold 0.22, Brier, plus base-rate Brier — never
  accuracy). Metrics are null until 20 rows have resolved and PR-AUC is null with one class
  (degenerate → null, never 0). A model refit starts a new segment; the headline scores the current
  segment only. `record()` refuses to append to a broken chain. Outputs: `data/ledger.parquet`,
  `data/live_record.json`, `data/badges/live_record.json` (shields.io endpoint schema), and the
  README block between `<!-- live-record:start/end -->` markers (fx universe only). CLI
  `python -m fxradar.ledger --record` / `make ledger`; both universes seeded (2026-08-17 close).
- Pipeline: new `ledger` stage after siren, before narrator; files written in the write stage
  (all-or-nothing preserved). `stage_forecaster` keeps `forecaster_meta` in ctx.
- README: **Track record — frozen test vs live forward record** headline table right under the intro
  (frozen 2019+ column beside the live column, warming up until 20 resolved, chain status, updated
  date). Badges are now REAL: `ci` (new `.github/workflows/ci.yml`: ruff + black + pytest + ledger
  chain verification, on every push/PR; data commits carry [skip ci]), `daily refresh`, `rust engine`
  workflow badges, and a dynamic `live record` shields endpoint fed by the pipeline. `OWNER/REPO`
  placeholder: `make set-repo REPO=you/name`, and the daily job substitutes `github.repository` on
  its first run. `daily.yml` now commits `README.md` alongside `data/`.
- App: Overview KPI tile "live record" (Brier since deploy vs base rate once warm, else warm-up
  progress); Methodology card "The live record — what the deployed models actually said".
- Tests (`tests/test_ledger.py`, 12 + 2 pipeline): newest-date-only + idempotent + forward-only
  append, tamper/delete/relabel breaks the chain, resolution == `forecaster.build_labels` exactly
  (day-by-day replay), idempotent resolve, summary null while warming up then equal to
  `forecaster.metrics`, current-segment scoring, single-class nulls, README block idempotent and
  local, warming-up renderers, twelve-run round trip through disk, broken chain refused, stage
  order + deferred writes; total 133.

## v2.8.0 — advisor + app shell (2026-08-18)

- `src/fxradar/advisor.py`: Market Stability Index (0–100; weights regime 0.35, change risk 0.20,
  siren 0.20, vol front 0.15, entropy 0.10; words Fair/Unsettled/Stormy/Severe), regime
  durability (1/(1−p) typical run vs current, memoryless note), risk budget (share of the user's
  own normal size: ×(1−risk) above 0.30, crisis ½, chop 0.8, siren >90 ×0.7, >98 → 0) with
  reasons, inverse-vol allocation, sizing calculator (capped 2×), `snapshot()` evidence base per
  universe/as-of, and `answer()` — LLM Q&A grounded ONLY in the snapshot with a guardrail system
  prompt (never direction/buy/sell/outside facts, cites fields) and template answers (direction
  questions are refused). Pipeline stage `advisor` writes `data/advisor.json` per universe.
- App shell: `app/app.py` is now a router (`st.navigation`: Radar → Overview, Advisor; Research →
  Strategy lab, Arcade; About → Methodology), pages moved to `app/views/`; shared sidebar
  (universe · market · scenario explorer) via `ui.scenario_controls`; KPI strip + alerts (crisis,
  siren, high change risk) on Overview; new Advisor view (stability gauges, durability, risk
  budgets with reasons, allocation, calculator, Ask the radar, snapshot expander); CSS polish
  (KPI tiles, section headers, alerts, buttons, expanders, nav). Methodology explains the index,
  durability, budget and the Q&A guardrails; README section.
- Tests: advisor logic (bounds/monotonicity, durability math, budget rules incl. no direction
  words, allocation, sizing, snapshot + template guardrails), router + advisor render, views
  paths; total 118.

## v2.7.0 — universes + scenario explorer (2026-08-18)

- `src/fxradar/universes.py`: one record per instrument set (pairs, tickers, bounds, splits,
  day-count, corrupted-print thresholds, cost model, official cross-check, forecaster pair
  one-hots, siren events, narrator words, artifact sub-directory). `fx` = the shipped defaults
  (bundle/goldens still replay bit-for-bit; Rust selftest PASS); `crypto` = BTC/ETH/LTC, train
  ≤ 2020, val 2021–22, test 2023+, `sqrt(365)`, 30 %/15 %/5 %/60 % print thresholds, 8 bp + 20×vol
  costs. `FXRADAR_UNIVERSE=<name>` selects it; `config.py` derives everything from it;
  `make train-universe UNIVERSE=crypto`; daily workflow refreshes both universes.
- De-hardwired FX-isms: pair dummies, siren events, narrator wording, ECB check, annualisation,
  cost defaults, export "must-include" goldens, chart underlay pair. `corr_20` now averages the
  components that exist on a date (a later-listed pair contributes nothing until it starts) —
  changed identically in Python and Rust; FX outputs unchanged.
- Crypto universe trained and shipped (`data/crypto`, `models/crypto`, `reports/crypto`):
  HMM (BTC calm 31 % vol → crisis 107 %; COVID/May-2021/Terra/FTX all `crisis`), forecaster
  PR-AUC 0.548 (logistic 0.488, base 0.228), siren lights every named crash, strategies +
  stress (S3 regime gate net Sharpe +0.07 test, breakeven 1.15×; the rest negative).
- App: sidebar **universe switch** on every page (pair labels via `Universe.display`),
  **scenario explorer** — named-episode jump list + free "as of" date; the whole page is
  rendered from data ≤ that date (cards, replayed template narration marked "(replay)", chart
  cut at the date with an "as of" marker, siren, loudest days), with a time-machine banner;
  deep links `?universe=&pair=&asof=`; log price axis for crypto. Strategy lab / Arcade /
  Methodology follow the selected universe.
- Tests: universe registry (FX defaults, crypto consistency), scenario explorer + universe
  switch flow, deep-link seeding; total 112.

## v2.6.0 — phase-18: regime orb (2026-08-18)

- `app/orb.py`: self-contained three.js (r128 from cdnjs) particle orb rendered via `st.iframe`
  (successor of `components.v1.html`), one hero orb for the selected pair beside the chart
  title (one WebGL context; the HTML card grid stays static — no layout shift). Four presets
  (calm slow drift / trend directional spin / chop high jitter / crisis fast chaos) in one JS
  object mirroring the Python `PRESETS` dict; regime → colour + motion, jitter × (1 +
  change_risk_5d), decaying pulse when anomaly_pct > 98. A display of the parquet numbers —
  computes nothing.
- Discipline: 900 particles (≤ 1 000), rAF paused on `document.hidden`, `prefers-reduced-motion`
  → gentle drift with zero jitter/chaos, three.js/WebGL failure → the flat regime dot in the same
  box (verified: fallback keeps the 220 px wrap height), hover/tap caption "what am I looking
  at", no sound, no faces, no orb on the reading pages. Snippet ≈ 7 KB; three.js ≈ 150 KB gz
  from CDN. Measured JS + render cost 0.23–0.34 ms per frame under headless software GL ≈ 2 %
  of one core at 60 fps (screens: `docs/screenshots/orb/orb_states.png` — calm, trend, chop,
  crisis, crisis pulse, reduced motion, fallback).
- Methodology page: one line on the mapping. `docs/DEMO_SCRIPT.md`: the orb beat. README: orb
  section + v3 react-three-fiber note. Test: orb render smoke (presets, pulse flag, fallbacks).

## v2.5.0 — phase-17: calibration arcade (2026-08-18)

- `src/fxradar/arcade.py`: sqlite store at `data/arcade.db` (calls, visits, badges, gallery
  opens, events; gitignored — user state, reset on free-tier redeploy, v3 Postgres makes it
  durable); one call per pair per ISO week; ANTI-ANCHORING enforced in Python —
  `pre_lock_payload` carries no model value (asserted), `place_call` stores the model's
  change_risk_5d at lock time and only `post_lock_view` reveals it; `resolve_calls` (pipeline
  stage `arcade`, write phase) resolves matured calls after 5 trading days from regimes.parquet
  and scores user and model with the Brier score on the identical question; season ledger
  (rolling Brier both sides, wins = lower Brier per call); watch streak (consecutive UTC days);
  ranks observer → forecaster → storm chaser → regime master driven ONLY by resolved calls and
  rolling Brier; five badges in one rule table; profanity-filtered nickname, no accounts.
- `data/storms.yaml`: five hand-curated storms (SNB 2015, Brexit 2016, GBP flash crash 2016,
  March 2020, 2022) with date/pair/siren percentile cross-checked against the artifacts and a
  3-line story each, `verified: true` — the developer should re-read them (rule 13).
- `app/pages/3_Arcade.py`: banner "a calibration game: forecasting practice, not trading.",
  nickname, observatory (rank, streak), season ledger, badges, call cards with slider + lock
  flow (model number appears only after the lock), storm gallery unlocked by opening a story,
  storage note. No urgency, no money, no trading language, zero nags without a nickname.
  Methodology page records the "methodology reader" badge event.
- Tests (`tests/test_arcade.py`, 8 + app cycle): Brier hand values; resolution flip on day 3
  vs day 6 vs not matured; lock-before-reveal (payload has no model value; one call/week);
  resolution + ledger; streak rollover at midnight UTC; rank rules; badge rules; nickname
  filter and storm loading. App test plays a full cycle: pre-lock render has no model value,
  post-lock shows it.

## v2.4.0 — phase-16: stress lab (2026-08-18)

- `src/fxradar/stress.py` + `python -m fxradar.stress` → `reports/stress_report.md` (one section
  per test, a verdict sentence each, summary table), `stress_bootstrap_dd.png`,
  `stress_robustness.png`, `data/stress_tests.json` for the app.
- Tests run: (1) historical replays — SNB week Jan 2015, COVID crash Feb–Mar 2020, 2022 —
  return / max DD / worst day per strategy + the siren stop's firing dates (197 pair-days);
  (2) cost shocks at 2×/3×/5× and the BREAKEVEN COST multiplier (S1 0, S2 0.1, S3 0, BLEND 0 —
  no strategy has a positive gross Sharpe on the test set except S2 barely, so there is no edge
  to pay costs from); (3) execution shock, one extra day of lag (Sharpe change −0.00…+0.19);
  (4) volatility shock, crisis returns ×1.5 (worst DD deepens 0.5 % only — the overlay takes risk
  off in crisis); (5) 20-day block bootstrap, 1 000 one-year paths (BLEND median max DD −6.2 %,
  5th-pct pain −10.2 %); (6) ±30 % parameter robustness heatmaps (BLEND net Sharpe band 0.86: a
  flat negative plateau — nothing overfit, nothing good). Nothing was re-tuned.
- Strategy-lab page: compact stress panel (breakeven table, replays, bootstrapped drawdowns +
  histogram). README results section updated with the strategy-layer verdict.
- Tests (`tests/test_stress.py`, 4): moving-block bootstrap preserves autocorrelation
  (vs day-shuffle) and shape; params override restores; breakeven semantics (positive gross →
  positive multiplier, negative gross → 0); window stats.

## v2.3.0 — phase-15: strategies and blend (2026-08-18)

- `src/fxradar/strategies.py`: S1 trend (clip(mom_20/3 %)), S2 mean reversion (−clip(z_5d, ±2)/2
  with z = 5-day return / expected std), S3 regime gate (S1 in trend, S2 in chop, ½·S1 in calm,
  flat in crisis) — mechanical rules, no fitted direction. Insurance overlay on every strategy:
  ×(1 − change_risk_5d) above 0.30, flat when anomaly_pct > 98 (siren stop), vol targeting to
  10 % per pair on the strategy's own trailing 60-day realised vol, leverage capped at 2×
  (engine `max_position`). Blend: monthly inverse-vol weights from trailing 120-day pooled net
  vol, lagged (causal). One PARAMS block, fixed on train+val, comment forbids further tuning;
  test 2019+ scored once.
- `reports/strategy_eval.md` + `strategy_equity.png` (net equity, EURUSD regime underlay,
  validation/test dividers): gross vs net for train/val/test, per-regime net Sharpe
  attribution, correlation matrix, the mutual-insurance verdict (blend max DD does NOT beat the
  best single strategy in the test sample), vol-target/cap note (cap binds 46–81 % of days →
  realised 6–9 %), honest closing paragraph. Test net Sharpe: S1_trend -1.23, S2_meanrev -1.36, S3_regime_gate -1.30, BLEND -2.18. Expected outcome, stated
  in advance: after realistic costs the edge is absent; the framework and the honesty are the
  deliverable.
- Artifacts: `data/backtests.parquet` (S1–S3 + BLEND), `data/strategy_metrics.json`,
  `data/strategy_attribution.json`. Dashboard page `2_Strategy_lab.py`: net equity, drawdowns,
  gross/net metrics with period selector, per-regime attribution, correlation, banner
  "research demonstration on daily data — not a live trading system".
- Tests (`tests/test_strategies.py`, 6): overlay forces flat on siren days and scales by risk;
  strategies in [−1, 1] and causal; regime-gate semantics; vol targeting on train (10 % ± 2 %
  or capped-and-below, never hotter); blend weights monthly/inverse-vol/causal; leverage never
  above cap in the saved backtests. Plus the Strategy-lab app smoke test.

## v2.2.0 — phase-14: backtest engine (2026-08-18)

- `src/fxradar/backtest.py`: `run_backtest(positions, prices, features, cost_cfg)` — daily bars
  only; THE LAG LAW inside the engine (positions shifted one day: a signal formed at close t
  earns t+1); `CostConfig(base_bps=1, vol_mult=80)` → cost_bps_t = base + vol_mult·vol_20_t
  (measured calm ≈ 5 bp, crisis 12–16 bp; crisis/calm 2.4× EURUSD, 3.1× GBPUSD, 8× USDCHF)
  charged on turnover |pos_t − pos_{t−1}|; daily frame + metrics gross AND net per pair and
  pooled (CAGR, ann vol, Sharpe, max drawdown, annual turnover, cost drag, hit rate);
  `metrics_table()`; `data/backtests.parquet` (date, strategy, pair, pos, ret_gross, ret_net,
  cost_bps) with the always-long demo strategy.
- Demo (always long, all pairs, 2005-03 → 2026-08): net CAGR −0.9 %, Sharpe −0.19, max DD −30 %.
- Tests (`tests/test_backtest.py`, 6): constant long = asset return − exactly one entry cost;
  daily sign flip cost bleed to the cent; THE FORESIGHT TEST (same-day-close signal: Sharpe > 10
  with the lag disabled, |Sharpe| < 1 with it enforced); cost monotonicity in vol_mult; clipping
  + gross/net contract; cost scaling. Note: the spec's `sign(ret_{t+1})` is written as
  `sign(ret_t)` in engine indexing — the sin being tested is contemporaneous lookahead.

## v2.1.0 — phase-13: axum service (2026-08-18)

- `rust/fxradar-serve` binary `fxradar-serve` (axum 0.8 + tokio + tracing): startup gate in
  order — load bundle → verify SHA-256 → run the full golden self-test in-process → only then bind.
  Failure logs the diff table via `tracing` and exits 1; `--skip-selftest` exists and logs a loud
  warning. Demonstrated: a tampered `goldens.parquet` is refused (hash mismatch); a corrupted
  golden with a matching hash is refused by the self-test (`change_risk_5d 5.0e-2 > 1e-6 ✗`,
  "REFUSING TO START").
- Endpoints: `GET /api/health` (bundle version, git commit, selftest status/timestamp/worst
  diffs, uptime, in-memory p50/p99 of scoring latency), `GET /api/regimes/{pair}` (latest row from
  `data/regimes.parquet` via a read-only state store, + `served_by`), `POST /api/score` (raw
  windows for all pairs → full Rust path → ScoredRow JSON). JSON errors with proper status codes
  (400 bad window / unknown pair, 404, 503, 500); request logging with latency (tower-http trace).
- Load check (`tools/load_check.py`, 1 000 real requests): server-side p50 0.42 ms / p99 0.48 ms,
  round trip p50 0.99 ms / p99 1.46 ms; recorded in `rust/BENCH.md`. Live proof: `/api/score` on
  today's USDCHF window reproduces the pipeline's numbers (risk 0.013451, anomaly pct 24.9).
- `rust/fxradar-serve/Dockerfile` (multi-stage rust → debian-slim) and `docker-compose.yml`
  (service :8080 with bundle + data mounted read-only, dashboard :8501 with `FXRADAR_API_URL`).
  Docker was not available on the build machine; the service was verified natively.
- Dashboard: `FXRADAR_API_URL` switch — weather cards take their latest state from
  `GET /api/regimes/*` with a "served by rust v2.1.0" badge next to the timestamp; default
  behaviour unchanged (parquet).
- README "Production serving" section with the wall diagram, the startup-gate story and the
  measured latencies. Rust integration tests: bundle replay + tampered manifest refused; rustfmt
  + clippy clean.

## v2.0.0 — phase-12: rust inference engine (2026-08-18)

- `rust/fxradar-serve/` (cargo crate, edition 2021): `bundle.rs` (manifest SHA-256 verification
  FIRST, serde structs for hmm json / sidecars / feature spec), `features.rs` (exact
  feature-spec semantics from raw price windows incl. pairwise as-of `corr_20`; warm-up 60 rows),
  `hmm.rs` (Gaussian log-likelihood with precomputed precisions/log-dets, forward filter with
  log-sum-exp, entropy, run lengths), `infer.rs` (`Engine`: forecaster.onnx + siren.onnx via
  `ort` 2.0.0-rc.13, Platt calibration, rank percentile → `ScoredRow`), `selftest.rs` + the
  `selftest` binary (parquet goldens → end-to-end replay → per-output max-abs-diff table, exit 2
  on divergence). `thiserror` error enum; no `unwrap`/`expect` in library code; no network, no
  file writes; no Python.
- Self-test on bundle v1.4.0 (302 goldens): PASS — features ≤ 1.1e-13, filtered probs ≤ 1.9e-13,
  regime labels exact, change_risk_5d 3.8e-7, anomaly_score 8e-13, anomaly_pct within one rank.
- Rust tests: constant series, hand-computed vol_20/mom_20/ret_1d, truncation invariance,
  logsumexp stability. `cargo clippy --all-targets -D warnings` clean, `cargo fmt` clean.
- `criterion` benchmark → `rust/BENCH.md`: 0.43 ms per full single-row path, ≈ 2 260 rows/s.
- CI: `.github/workflows/rust.yml` (fmt, clippy, tests, selftest against the committed bundle).
- Bundle rebuilt (manifest git commit/timestamp); export doc note that `probabilities` is a plain
  [n, 2] tensor.

## v1.4.0 — phase-11: model bundle export (2026-08-18)

- `src/fxradar/export.py` + `python -m fxradar.export` → `models/bundle_v1.4.0/`, the ONLY
  artifact that crosses the wall (json/onnx/yaml/parquet — no pickle): `hmm_{pair}.json`
  (means, covariances, precomputed Cholesky-derived precisions + log-dets, transmat, startprob,
  scaler, frozen state names), `forecaster.onnx` (+ sidecar with feature order, Platt a/b,
  threshold), `siren.onnx` (float64, output reshaped to (n, 9); sidecar with scaler + sorted
  calm-train scores), `feature_spec.yaml`, `goldens.parquet` (302 rows across pairs × years ×
  regimes incl. USDCHF 2015-01-15/16; raw 600-day price windows for all three pairs + Python's
  exact features/probs/outputs), `manifest.json` (semver, git commit, model versions, parity,
  tolerances, SHA-256 of every file).
- ONNX parity recorded in the manifest: forecaster max |Δp| 2.7e-7 (16 660 rows), siren 7.1e-15.
- `export.replay_goldens`: the executable contract — from raw windows + bundle files only,
  reproduce every golden (features ≤ 1e-13, probs ≤ 2e-13, change_risk 3.8e-7, anomaly_score
  9e-13; anomaly_pct within one rank step, a documented rank-statistic tolerance).
- `docs/bundle_format.md`; export added as the last step of `make refit` and `refit.yml`.
- Tests (`tests/test_export.py`, 5): manifest hashes verify, tampering detected, HMM json
  matches the saved model (precision × cov = I, log-det), ONNX parity on fresh rows, golden
  round trip. Dependencies: onnx, onnxmltools, skl2onnx, onnxruntime, pyyaml.

## v1.3.1 — phase-10: polish (2026-08-18)

- README rewritten: hero screenshot, pitch, live-link placeholder, mermaid architecture, "How it
  works", Results with the frozen test-set scoreboard + calibration plot, Limitations promoted,
  repo tour, run locally, deploy, disclaimer, badges.
- `docs/model_cards.md` (HMM, forecaster, siren, narrator), `docs/INTERVIEW_NOTES.md` (nine
  answers in the developer's voice, each with a hard follow-up), `docs/DEMO_SCRIPT.md`
  (90-second walkthrough), fresh `docs/screenshots/dashboard.png`.
- Code pass: ruff + black clean, return-type hints on all public functions, build-kit files
  (`START_HERE.md`, `USAGE.md`) moved to `docs/`, no stray files. 77 tests green.

## v1.3.0 — phase-09: narrator (2026-08-18)

- `src/fxradar/narrate.py`: `build_stats(pair)` (numbers only: regime, regime_prob,
  days_in_regime, change_risk_5d, top_drivers, anomaly_pct, nearest-neighbour date, 5-day
  return); `narrate(stats)` via the Anthropic SDK — model `claude-haiku-4-5`, temperature 0.3,
  max_tokens 350, the verbatim guardrail system prompt, user content = the stats JSON only;
  key from env or Streamlit secrets; SDK retries (2, backoff); `template_narrate` writes the
  same three sentences deterministically; `narrate_with_fallback` never raises. Output
  `data/report.json` = {pair: {text, generated_at, source: "llm"|"template", stats}}.
- Pipeline stage `narrator` registered LAST; without a key the pipeline succeeds on the
  template path (verified). `daily.yml` passes the optional `ANTHROPIC_API_KEY` repository
  secret as an env var (empty → template).
- Dashboard: quote-style narration on every weather card with an AI/auto badge and timestamp;
  the app never calls the API (reads `report.json` only).
- README: how to add the key (GitHub secret, Streamlit secrets), cost estimate ≈ 5 ¢/month.
- Tests (`tests/test_narrate.py`, 5): template = exactly three sentences containing the regime
  and the risk figure (+ neighbour only when anomaly_pct > 90); missing key never raises; API
  failure falls back; mocked client receives the system prompt, model/temperature/max_tokens,
  and ONLY JSON-derived user content; build_stats types.

## v1.2.0 — phase-08: anomaly siren (2026-08-18)

- `src/fxradar/siren.py`: `MLPRegressor(hidden_layer_sizes=(8, 3, 8), max_iter=3000,
  early_stopping=True, random_state=42)` autoencoder on the 9 continuous features, scaler +
  model fit ONLY on train-period calm days with regime_prob > 0.7 (2 788 days, 2005-04-07 →
  2016-12-30), pooled across pairs, no pair one-hots (pair-agnostic by design — documented).
- Scoring: `anomaly_score` = mean squared reconstruction error; `anomaly_pct` = percentile
  against the calm-train distribution; per-feature squared errors + nearest historical
  neighbour (same pair, train period, ±10 days excluded) in `data/siren_detail.parquet`
  (for the phase-09 explainer). Scoring is truncation-invariant (tested).
- `reports/siren_validation.md` + `siren_anomaly_pct.png`: SNB 2015-01-15 is USDCHF's
  loudest day in history (rank 1, pct 100); Brexit 2016-06-24 rank 1 for GBPUSD; the
  2016-10-07 flash crash pct 100 (rank 139); March 2020: 68–82 % of days ≥ 98th pct. Honest
  reading: many merely-volatile days also scream; it detects, it does not predict.
- `models/siren_v1.2.0.joblib` (dict payload); manifest entry; pipeline stage `siren`
  registered — `regimes.parquet` now matches the full contract (model_version
  "hmm=0.4.0|fc=1.1.0|siren=1.2.0").
- Dashboard "Anomaly siren" section: SVG dial per pair (muted <90, amber 90–98, red >98),
  2-year sparkline, "Loudest days in history" table for the selected pair.
- Tests (`tests/test_siren.py`, 6): (8,3,8) architecture, scaler/model fit only on calm train
  days (date range + labels asserted), truncation invariance, percentile + outlier behaviour,
  neighbour exclusion window, saved-model SNB check.

## v1.1.0 — phase-07: forecaster (2026-08-18)

- `src/fxradar/forecaster.py`: pooled XGBoost classifier for "regime changes within the next
  5 trading days". Labels look forward; every feature is causal (matrix truncation-invariance
  test). Features exactly per spec (10 numeric incl. filtered HMM outputs + 3 regime one-hots
  + 2 pair one-hots). Time-ordered splits with a 5-day embargo on both sides of every boundary
  (tested). Fixed hyper-parameters, `scale_pos_weight` from train (4.88), early stopping on
  val (iteration 283). No grid search — deliberate.
- Probabilities are Platt-recalibrated on VALIDATION (a=0.95, b=−1.30): `scale_pos_weight`
  makes raw probabilities over-predict (raw Brier 0.128 vs 0.102 calibrated); both are shown.
  Threshold 0.22 chosen on val for recall ≥ 60 %.
- `reports/forecaster_eval.md` (+ `forecaster_calibration.png`, `forecaster_shap.png`), test
  set scored ONCE and frozen: PR-AUC 0.548 vs logistic 0.431, base rate 0.162, one-feature
  rule 0.143; precision 0.45 / recall 0.59 at the threshold; Brier 0.102 (logistic 0.116).
  Honest interpretation paragraph. Never accuracy.
- SHAP TreeExplainer: beeswarm png; per-day top-3 |SHAP| feature names → `top_drivers`.
- Model persisted as `models/forecaster_v1.1.0.json` (+ `.meta.json` with threshold,
  calibration, features, scoreboard); registered in `models/manifest.json`. Pipeline stage
  `forecaster` registered in `run_daily.py`; `regimes.parquet` now carries `change_risk_5d`
  and `top_drivers` (model_version "hmm=0.4.0|fc=1.1.0").
- Dashboard: "5-day change risk" gauge on every weather card (muted <20 %, amber 20–40 %,
  red >40 %) with the top drivers beneath.
- Tests (`tests/test_forecaster.py`, 8): label semantics, embargo gaps, matrix truncation
  invariance, exact feature list, threshold rule, Platt calibration recovers a known
  distortion, top-driver extraction, saved-model contract.

## v1.0.1 — phase-06: automation (2026-08-18)

- `pipelines/run_daily.py`: single orchestrator — stages `data → features → hmm → write`,
  registered with one line each (`register(name, fn)`) so phases 07–09 plug in. Models are
  LOADED (from `models/manifest.json`), never fitted. All compute runs in memory and every
  artifact is written in the final stage only, so any failure leaves `data/` untouched
  (verified: simulated failure → exit 1, files unchanged). Per-stage timings logged; full run
  ≈ 4 s locally. Idempotent: a rerun produces byte-identical parquet files. Writes
  `data/pipeline_status.json` (last run, data-through date, row counts, model versions, ECB
  check, timings) — the app shows "updated … UTC" from it. `FXRADAR_SIMULATE_FAILURE=<stage>`
  rehearses the failure path.
- `.github/workflows/daily.yml`: cron weekdays 06:00 UTC + `workflow_dispatch`; Python 3.11
  with pip cache; runs the pipeline; commits `data/` as `data: daily refresh [skip ci]`;
  `permissions: contents: write`; no secrets.
- `.github/workflows/refit.yml` (manual, inputs train_end + version) and `make refit
  TRAIN_END=… HMM_VERSION=…`: deliberate expanding-window refit that bumps the model version
  via `models/manifest.json`, regenerates the validation report and re-scores.
  `python -m fxradar.hmm_model` gained `--train-end/--version`.
- README: "Run locally" + "Deploy" (GitHub → Streamlit Community Cloud click-path, secrets
  note for phase 09, refit policy, failure honesty).
- Tests (`tests/test_pipeline.py`): success writes all artifacts + status; failure leaves the
  last good state and exits nonzero; simulated-failure env var; stage order.

## v1.0.0 — phase-05: dashboard v1 (2026-08-18) — first shippable

- `app/ui.py` owns the look: Google Fonts (Inter + JetBrains Mono), Streamlit chrome hidden,
  card class (#131A26 surface, 1px #232D3F border, 12px radius, 20px padding), regime pills
  in the four regime colours, one Plotly dark template (`fxradar_dark`) reused everywhere,
  helpers `regime_pill`, `card`, `confidence_bar`, `sparkline_svg`, `html_table`, `sidebar`,
  `footer`.
- `app/app.py`: header (wordmark, "market weather, updated daily", right-aligned "Data
  through …" from the artifact); hero row with one weather card per pair (pair, big regime
  pill, confidence bar, "day N of this regime", last close, inline-SVG 20-day sparkline);
  main panel with pair selector — Plotly close chart with merged regime bands (shapes), the
  out-of-sample divider at 2017-01-01 with annotation, 1y/3y/max range buttons; out-of-sample
  regime anatomy table (same definitions as the phase-04 report). Reads only
  `data/regimes.parquet` + `data/prices.parquet` (light pandas, no model imports).
- `st.cache_data` loaders keyed by file mtime; measured first paint ≈ 1.2 s cold, 0.1 s warm.
- `app/pages/1_Methodology.py`: pipeline, HMM + mood metaphor, filtered vs smoothed in two
  sentences, out-of-sample note, full Limitations. Disclaimer in sidebar + footer on every page.
- `docs/screenshots/dashboard_v1.png` (headless Chrome via `tools/screenshot.py`, main
  content crop). Sidebar holds only the pair selector and the disclaimer.
- Tests (`tests/test_app.py`): both pages render from artifacts without exceptions, carry the
  disclaimer in sidebar and footer, one Plotly figure, load-time budget.

## v0.5.0 — phase-04: hmm validation (2026-08-18)

- `src/fxradar/validate.py` + CLI `python -m fxradar.validate` → `reports/hmm_validation.md`
  with `regimes_timeline_{pair}.png` (close + regime bands, "out-of-sample →" divider at
  2017-01-01, design-system colours) and `regime_durations.png`.
- Sections: (1) regime anatomy train vs OOS (frequency, mean duration, ann. vol, mean daily
  return, worst drawdown inside each label); (2) 5-seed stability table with an honest
  paragraph (EURUSD mean 71 % < 80 % warning; trend/chop split is the fragile part);
  (3) naive baseline — "stressed" when vol_20 > trailing 250-day 80th percentile — agreement,
  Cohen's kappa and dated lead/lag episodes (the HMM does not systematically lead: 4 leads vs
  14 lags across matched episodes); (4) economic-meaning check — toy MA(50/200) rule's Sharpe
  per regime OOS: the "trend best / chop worst" claim FAILS and is reported as such;
  (5) plots; (6) Limitations (daily data, label noise, descriptive not predictive, frozen
  naming rule + SNB, single train window, Gaussian emissions).
- Tests (`tests/test_validate.py`, 7): max drawdown, Sharpe, run lengths, causal naive rule
  (truncation), episode/lead-lag logic, lagged MA rule (+ causality), table shapes.

## v0.4.0 — phase-03: hmm with filtered probabilities (2026-08-18)

- `src/fxradar/hmm_model.py`: one 4-state `GaussianHMM(covariance_type="full", n_iter=1000,
  random_state=42)` per pair on `[ret_1d, vol_20, mom_20]`, StandardScaler and model fit on
  the TRAIN window only (≤ 2016-12-31, `config.TRAIN_END`).
- `filtered_probs`: forward algorithm (per-frame Gaussian log-likelihoods + transition matrix,
  logsumexp-normalised each step) → P(state_t | obs ≤ t). Smoothed posteriors
  (`predict_proba`) are never used for any output. Tested against brute-force prefix
  recompute (60-row toy, atol 1e-8) and for truncation invariance; a companion test shows
  smoothed posteriors are NOT truncation-invariant.
- Frozen naming rule from train-period per-state stats: lowest mean vol_20 = calm, highest =
  crisis, of the middle two the larger |mean mom_20| = trend, other = chop. Persisted with the
  model. Honest note: for USDCHF the "crisis" state collapsed onto the 20 SNB-shock days
  (2015-01-16 → 2015-02-12; mean vol_20 65 %), so its 2008–11 stress carries the "chop" name
  — reported as-is for the phase-04 honesty report (clipping inputs was tried and made seed
  stability worse, so the spec-exact setup is kept).
- Outputs per pair/day: `regime`, `regime_prob`, `hmm_entropy` (nats, max ln 4),
  `days_in_regime`, `vol_trend` (sign of the 10-day change in vol_20), `model_version`
  ("hmm=0.4.0"). Written to `data/regimes.parquet` (the CLAUDE.md contract name — no
  `_base` variant; phases 07/08 enrich it in place) and the three post-HMM columns appended
  to `data/features.parquet`.
- Models: `models/hmm_{pair}_v0.4.0.joblib` (plain dict payload: model, scaler, mapping,
  train_end, version, features). CLI `python -m fxradar.hmm_model [--refit] [--stability]`
  loads saved models by default (never refits in the daily path).
- Results: mean regime_prob 0.96–0.98; transition-matrix diagonals 0.95–0.985 (sticky).
  5-seed label agreement vs seed 42: EURUSD 0.53–1.00 (mean 0.71, below the 80 % warning),
  GBPUSD 0.40–1.00 (mean 0.86), USDCHF 0.59–0.99 (mean 0.81) — EM local optima; discussed
  honestly in phase 04.
- Tests (`tests/test_hmm.py`, 10): filtering vs brute force, causality, frame log-likelihood
  vs hmmlearn, naming rule, run length, score outputs + truncation invariance, train-only
  scaler, bundle round trip, saved-model sanity (diag > 0.8, 4 states, permutation),
  contract of the artifacts.

## v0.3.0 — phase-02: feature engine (2026-08-18)

- `src/fxradar/features.py`: `build_features(prices)` computes the base contract features per
  pair — `ret_1d` (log return), `vol_20`/`vol_60` (rolling sample std × √252, ddof=1),
  `vol_ratio` (5-day vol / vol_60, the "storm front"), `mom_20`, `rng_hl` (10-day mean of
  (high−low)/close), `corr_20`, `ret_5d_abs`. Strictly causal; first 60 rows per pair dropped
  as warm-up; no scaling (models own their scalers).
- `corr_20` — deliberate, documented readings of the spec: (a) returns are put on one sign
  convention before correlating (USDCHF negated via `config.USD_BASE_PAIRS`, so every column
  is foreign-currency-vs-USD; the literal un-flipped mean gives medians −0.07/+0.04/−0.71
  because the +/− legs cancel, the flipped one gives 0.75/0.64/0.71 — a comparable
  "dollar-factor strength" across pairs); (b) each of the two correlations is computed on the
  dates both pairs traded and as-of aligned backward onto the pair's own dates (a hole in one
  pair only freezes that leg); (c) an undefined (zero-variance) window yields NaN, never a
  stale value.
- CLI `python -m fxradar.features`: prices.parquet → `data/features.parquet` (16 660 rows ×
  10, 2005-03-28 → 2026-08-17), prints shape, rows per pair, date range and NaN report (0).
- Tests (`tests/test_features.py`, 12): contract schema/dtypes, no post-warm-up NaNs, toy
  constant series, hand-computed vol_20/vol_60/vol_ratio/mom_20/ret_1d/rng_hl/ret_5d_abs,
  corr_20 mean-of-two + sign convention + hole + zero-variance semantics, TRUNCATION
  INVARIANCE (drop last 30 rows per pair; `assert_frame_equal(check_exact=True)`), one-pair
  truncation, shifting-start drift check. Verified on the full real history for k = 1, 5, 30.

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
