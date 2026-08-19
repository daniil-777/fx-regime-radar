# Adaptation report — prompts matched to your actual repo (from claude_2.zip, phases 00–18)

## Where everything goes
1. Every `phase-*.md` in this pack → `.claude/commands/` (the pack's `phase-19.md`
   REPLACES your current one — same 3D content, fixed version line + pre-filled repo map).
2. `design-target-mockup.html` → `design/` at the repo root (create the folder). Commit it.
3. `ROADMAP.md` + this file → `docs/` (reference only).
4. Run order (numbers ≠ order): **/phase-20 first — the ledger clock** → 21 → 22 → 23 →
   24 → 25 → 26 → 27 → 28 → 29 → 30. Phases 19 (3D) and 31 (UI) are display-only:
   run any time after 20; run 31 before 27 so the weekly report is born styled.

## Confirmed repo map (extracted from your own phase files)
| Thing | Actual |
|---|---|
| Package / app / pipeline | `src/fxradar/` · Streamlit `app/app.py` + `app/ui.py` + `app/pages/` · `pipelines/run_daily.py` (register-a-step pattern) |
| Make targets | setup · test · lint · fmt · run · pipeline |
| Pairs | EURUSD, USDCHF, GBPUSD (no EURCHF pair — added as context series in phase 23) |
| Data artifacts (committed) | `data/prices.parquet` (OHLC ✓ → Yang-Zhang feasible), `features.parquet`, `regimes_base.parquet`, `regimes.parquet`, `report.json`, `backtests.parquet`, `arcade.db`, `storms.yaml` |
| Splits | train ≤ 2016-12-31 · val 2017–2018 · test 2019+ · 5-day embargo · H = 5 (`change_risk_5d`) |
| Regime outputs | filtered probs (custom forward algo), regime/regime_prob/hmm_entropy/days_in_regime/vol_trend; mapping calm/trend/chop/crisis frozen |
| Siren | `anomaly_score`, `anomaly_pct` (+ per-feature errors, nearest neighbor); SNB 2015 validated on USDCHF |
| Narrator | `src/fxradar/narrate.py`, Haiku + `template_narrate` fallback, `data/report.json` |
| Rust | `rust/fxradar-serve/`: bundle gate + golden selftest, axum `/api/health` `/api/regimes/{pair}` `POST /api/score`, `tracing` ✓, docker-compose, `rust/BENCH.md` |
| The wall | `models/bundle_v*/` (json/onnx/yaml/parquet only) — **any feature change must not break feature_spec/goldens** |
| CI | daily Action 06:00 UTC commits `data/` → this gives phase-20 free external timestamps |
| Existing design system | CLAUDE.md tokens, Inter + JetBrains Mono, #131A26/#232D3F, `app/ui.py` owns CSS + one Plotly template, regime pills, orb presets mirror the palette |
| Tags | sequential minors; you're at v2.6.0 after phase 18 → next tag v2.7.0, then keep counting |

## What I changed in the prompts (beyond renumbering)
- **phase-19 (3D)**: version line fixed to "next minor"; repo map pre-filled; explicit
  rule: the orb stays — the new 3D lives on its own "Probability space" tab.
- **phase-20 ledger**: registers as a `run_daily` step; reads `data/regimes.parquet`;
  ledger at `data/ledger.parquet` — the existing daily Action commit IS the notarization
  (plus `data/ledger_head.txt`); drift on your 9 features; HMM staleness via your saved
  models' filtered log-lik.
- **phase-21 BOCPD**: third voter = your phase-04 naive rule (vol_20 > trailing 80th pct) — it already exists.
- **phase-22 conformal**: calibration = the 2017–2018 val years, with the dual-use
  (threshold was chosen there too) documented honestly; test 2019+ stays untouched.
- **phase-23 calendar**: all new features go to `data/features_ext.parquet`, consumed by a
  CHALLENGER forecaster only — `feature_spec.yaml`, the bundle, goldens, and Rust stay
  byte-identical (golden rule 11 protected). Yang-Zhang ships as `vol_20_yz` there; the
  wall adopts it only at the next scheduled bundle rebuild.
- **phase-24 productize**: EXTENDS the existing axum service (keys, HMAC webhooks, utoipa
  /docs, Prometheus /metrics, widget.js, tiers) — startup gate and selftest untouched;
  numbers appended to `rust/BENCH.md`; deploy notes target your Oracle VM.
- **phase-25 treasury**: no advisor module exists → builds `src/fxradar/treasury.py` fresh;
  pipeline writes `data/treasury_risk.json`; Streamlit page does arithmetic only; optional
  axum route reads the artifact (no model math in handlers, your rule).
- **phase-26 storms**: no scenario explorer exists → replay = truncated reruns of the real
  scoring path (reusing phase-16 window logic); SNB 2015 told via USDCHF where your siren
  is already validated, with the EURCHF peg-blindness sidebar once phase 23 adds that series.
- **phase-29/30 letters**: FinBERT moved OUT of requirements/CI (separate
  `requirements-nlp.txt`, VM/local only — your sklearn-only, 5-minute-CI design survives);
  LLM leg reuses the phase-09 anthropic client + key handling.
- **phase-31 UI**: evolves your existing system instead of replacing it — updates CLAUDE.md
  design tokens, `app/ui.py`, `.streamlit/config.toml`, the Plotly template, regime pills,
  AND the orb's JS preset colors (they mirror the palette — easy to forget); orb is
  grandfathered as the one ambient element; fonts move Inter/JetBrains → IBM Plex/Space
  Grotesk at the existing Google Fonts import point.

## Confirm at Step 0 anyway
The zip contained only `.claude/commands/` — if you built anything beyond phase 18 that
isn't a command file (extra pages, extra pairs), say so when a phase prints its repo map.
