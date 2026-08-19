---
description: Phase 19 — signature 3D visuals: regime tetrahedron + market landscape (display layer only) (next minor tag)
---

Read CLAUDE.md golden rules 1 and 2 (causality, train/test discipline).
Goal: a `viz3d` module, one new dashboard page, and a README GIF.

This phase is DISPLAY LAYER ONLY: zero changes to features, models, labels, or
any pipeline output. It needs only what phases 00–08 already produce (filtered
probabilities, features, siren), so it runs any time after phase 20
(the ledger). Note on order: numbers are names, not sequence — build the
phase-20 ledger FIRST, then this whenever you like. Keep the phase-18 orb:
the new 3D lives on its own "Probability space" tab and never replaces it.

## Step 0 — map the real repo before writing any code
Pre-filled from your phase files — verify each, report drift, and WAIT:
1. Package `src/fxradar/`; dashboard `app/app.py` + `app/ui.py` (owns the
   Plotly template) with pages under `app/pages/`.
2. Filtered probabilities from `src/fxradar/hmm_model.py` → regimes_base
   parquet; frozen calm/trend/chop/crisis mapping persisted with the models.
3. Siren = anomaly_pct in `data/regimes.parquet`.
4. HMM inputs [ret_1d, vol_20, mom_20], scaler fit on train ≤ 2016-12-31.
5. Pairs EURUSD (flagship), USDCHF, GBPUSD; new page = `app/pages/`.
6. Make targets: test, pipeline, run; tests under `tests/`.
Print a short adaptation table (planned name → actual name) and WAIT for my
confirmation before building anything. Then apply the requirements below using
the actual names; the behavior, tests, and Verify block stay exactly as
written. If you find something broken or ugly along the way, note it in the
report — do not fix or refactor it in this phase.

## Task
Two mathematically honest 3D visualizations from data the pipeline already
produces, plus a rotating GIF for the README header:

A) Regime tetrahedron — the 4-state filtered probabilities sum to 1, so every
   day is a point in a 3-simplex (a tetrahedron). Plot the market's daily
   path through it.
B) Market landscape — 3D embedding of all historical days, colored by regime,
   with the last 60 days as a trail and today highlighted.

## Requirements
1. `simplex_coords(probs: ndarray[T,4]) -> ndarray[T,3]` in the viz3d module
   (path per Step 0):
   - Vertex matrix `V = [[1,1,1],[1,-1,-1],[-1,1,-1],[-1,-1,1]]`, rows in the
     named-regime order [calm, trend, chop, crisis] (or the repo's actual
     four names in the frozen-mapping order). The caller passes probability
     columns already ordered by that frozen mapping — take the mapping as an
     explicit argument and assert the order; never infer it.
   - Return exactly `probs @ V` (no scaling, no centering).
   - Validate: every row sums to 1 within 1e-9 and is non-negative; raise
     ValueError otherwise. The uniform row [0.25, 0.25, 0.25, 0.25] must map
     to the origin (the centroid).

2. `tetrahedron_figure(pair, color_by="time") -> plotly Figure`:
   - 6 edges as thin neutral Scatter3d lines; 4 vertex markers labeled with
     regime names, using the dashboard's existing regime palette.
   - Daily path from FILTERED probabilities only — never smoothed — as
     `mode="lines+markers"`, marker size 2–3, colored by day index
     (`color_by="time"`) or by siren with a colorbar (`color_by="siren"`).
   - Today: larger marker with a ring. Hover: date, the four regime
     probabilities rounded to 2 dp, siren.
   - Hide ALL axes, ticks, gridlines, and background planes in the scene and
     set `aspectmode="data"`. Simplex coordinates have no units; visible axes
     would imply meaning that does not exist.

3. `landscape_figure(pair, method="pca") -> Figure`:
   - Inputs: the standardized model feature matrix from Step 0 item 4, scaled
     with the existing train-only StandardScaler discipline.
   - Embedding via `fit_landscape_embedding(features, train_end=TRAIN_END)`:
     `PCA(n_components=3, random_state=42)` FIT ON TRAIN ROWS ONLY, then
     transform the full history. Store `train_end` and the number of fit rows
     as attributes on the returned object so the train-only fit is auditable,
     and persist the fitted PCA with joblib next to the other frozen
     artifacts.
   - `method="umap"` is allowed only if umap-learn is already importable; PCA
     is the default. Do NOT add umap-learn to requirements.
   - Figure: all days as Scatter3d points colored by regime (same palette);
     the last 60 days as a connected trail with increasing opacity; today as
     a distinct larger marker with a ring. Hover: date, regime, siren.

4. Dashboard: add one new page/tab named "Probability space" with (A) above
   (B), a pair selector, and a color-by toggle for (A). Two or three plain
   sentences of explainer copy per figure: what a corner means, what the
   center means, what a cluster of points means. Every pre-existing panel
   stays exactly as it was, and stays 2D.

5. `scripts/make_gif.py` + `make gif` target:
   - Render (A) for the flagship pair (EURUSD if present, else the first
     configured pair) with the camera orbiting: 72 frames at 5° steps, fixed
     elevation, width 600 px, per-frame PNG via kaleido `fig.write_image`,
     stitched with imageio into `assets/tetrahedron.gif`.
   - Target < 5 MB; if over, reduce frames or width until under.
   - Embed at the top of README.md with the one-line caption:
     "Every day's regime probabilities are one point in this tetrahedron —
     this is the full history moving through them."
   - kaleido and imageio go in dev dependencies only.

6. Tests in `tests/test_viz3d.py`:
   - Exactness: `simplex_coords([[1,0,0,0]])` equals vertex 0 exactly; the
     uniform row maps to the origin within 1e-12; on random valid rows the
     output equals `probs @ V` bit-for-bit.
   - Validation: rows not summing to 1, or containing negatives, raise.
   - Order guard: passing a state mapping whose order disagrees with the
     vertex labels raises.
   - Leakage: the fitted embedding's stored `train_end` equals TRAIN_END and
     its fit-row count equals the number of train rows — no future dates in
     the fit.
   - Determinism: two calls to `landscape_figure` yield identical coordinates
     (fixed random_state).

## Do not
No changes to any pipeline module, feature, model, or artifact — if a diff
touches anything outside the viz3d module, the dashboard page,
scripts/make_gif.py, tests, assets, and README, stop and reconsider. No
smoothed probabilities anywhere. No three.js or axum widget yet (that reuses
phase-24 infrastructure later). No new runtime dependencies; kaleido and
imageio are dev-only. No refactors of code discovered in Step 0. No 3D on any
other dashboard panel: the daily operational views stay 2D on purpose — that
restraint is part of the design and part of the interview story.

## Verify
- `make test` green, including the untouched truncation-invariance test.
- Regenerate the pipeline outputs and confirm sha256 of features.parquet and
  the regime output files are byte-identical to before this phase (proves
  display-only).
- Dashboard screenshot of both figures. Rotate the tetrahedron and spot-check
  3 dates: hover probabilities must match the regime table for those dates.
- `assets/tetrahedron.gif` exists, is < 5 MB, and plays in the README on
  GitHub.
- Show me `simplex_coords` and the `fit_landscape_embedding` fit call side by
  side so I can see the train-only slice with my own eyes.
- CHANGELOG, commit `phase-24: signature 3d visuals`, tag the next minor (you are at v2.6.0 after phase 18).

## Teach me
Explain: why a 4-state probability vector lives exactly in a tetrahedron, and
what changes with 3 states (a flat triangle) or 5 (a 4-simplex that must be
projected — and why that projection starts costing honesty); why the
landscape's PCA must be fit on train only even though "it's just a plot"; why
the path must use filtered, never smoothed, probabilities. Then quiz me:
(1) an interviewer says "3D charts are gimmicks" — give my 60-second defense
of this one; (2) what would it mean if the path spent most of its time near
the centroid? Critique my answers.
