---
description: Phase 05 — styled Streamlit dashboard, first shippable release (v1.0.0)
---

Read CLAUDE.md, especially the design system and golden rule 8. Build the app.
This phase decides whether the project LOOKS hired-grade — be a perfectionist.

## Task
Build `app/app.py`, `app/ui.py`, and `app/pages/1_Methodology.py` into a fast,
dark, card-based dashboard that reads only `data/regimes_base.parquet`.

## Requirements
1. `app/ui.py` owns the look: inject CSS once (Google Fonts import for Inter +
   JetBrains Mono; hide Streamlit's menu, footer and deploy button; card class
   with #131A26 surface, 1px #232D3F border, 12px radius, 20px padding; regime
   pill class per regime color). Define one Plotly dark template with the
   design-system palette and reuse it for every figure. Helper functions:
   `regime_pill(name)`, `card(...)`, `confidence_bar(p)`.
2. Header: wordmark "FX Regime Radar", subtitle "market weather, updated daily",
   and "Data through {max date}" from the parquet — right-aligned, muted.
3. Hero row: one weather card per pair — pair name, big regime pill, confidence
   bar for regime_prob, "day N of this regime", 20-day mini sparkline of close.
4. Main panel with a pair selector: Plotly chart of close with regime-colored
   background bands (use shapes, merge consecutive same-regime days into single
   bands for performance), the out-of-sample divider line at 2017-01-01 with
   annotation, range selector buttons (1y, 3y, max).
5. Below: regime anatomy table for the selected pair (from phase-04 stats,
   test period), styled to match.
6. Methodology page: plain-English explanation of the pipeline, the HMM, the
   mood metaphor, filtered vs smoothed in two sentences, and the full
   Limitations section. Footer on every page: the disclaimer (rule 7).
7. `st.cache_data` on all loaders keyed by file mtime; total first paint about
   one second. No computation beyond light pandas.
8. Take a full-page screenshot (headless is fine) to
   `docs/screenshots/dashboard_v1.png`.

## Do not
No default Streamlit look anywhere. No model imports in the app. No emoji as
UI. No sidebar clutter — sidebar holds only the pair selector and the
disclaimer.

## Verify
- `make run`; walk me through the screen, then show the screenshot file.
- Confirm load time by timing the loaders. `make test` green.
- CHANGELOG, commit `phase-05: dashboard v1`, tag `v1.0.0`. This is shippable.

## Teach me
Explain: why artifacts-only makes the app fast and cheap, and two design
choices that make dashboards feel professional. Then two interview questions
about productionizing ML outputs; critique my answers.
