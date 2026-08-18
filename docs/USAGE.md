# FX Regime Radar — build kit (read this first)

This folder is a complete, ordered prompt system for building the FX Regime Radar
with Claude Code. `CLAUDE.md` is the project constitution Claude reads on every
session. Each file in `.claude/commands/` is one build phase, and its filename is
the command you type: `phase-01-data.md` → you type `/phase-01-data`.

## One-time setup

1. Install prerequisites: Python 3.11+, git, and Claude Code
   (install guide: https://docs.claude.com/en/docs/claude-code/overview — the CLI
   ships as the npm package `@anthropic-ai/claude-code`).
2. Create an empty folder, e.g. `fx-regime-radar/`, and copy the CONTENTS of this
   kit into it, so the repo root contains `CLAUDE.md` and `.claude/commands/`.
3. Open a terminal in that folder and run `claude`. Type `/` — you should see the
   phase commands listed. You're ready.

## The loop (repeat for every phase, in order)

1. Type the phase command, e.g. `/phase-00-scaffold`, and let Claude Code work.
2. Run the phase's verify commands YOURSELF in the terminal. Green means done;
   red gets pasted back to Claude in full.
3. Do the "teach me" part seriously — answer the two interview questions it asks
   you. This is how the app becomes YOUR knowledge instead of generated code.
4. Confirm the commit and version tag happened (`git log --oneline`).
5. Stop or continue. One phase per sitting is a perfectly good pace.

## Phase map

| Command | Builds | Ships as |
|---|---|---|
| /phase-00-scaffold | repo skeleton, tooling, CI-ready tests | v0.1.0 |
| /phase-01-data | price loader + ECB cross-check | v0.2.0 |
| /phase-02-features | feature engine + leakage tests | v0.3.0 |
| /phase-03-hmm | regime model, filtered probabilities | v0.4.0 |
| /phase-04-validate-hmm | honesty report: stability, baselines | v0.5.0 |
| /phase-05-dashboard | styled Streamlit app — first shippable | v1.0.0 |
| /phase-06-automation | daily GitHub Action + deploy | v1.0.1 |
| /phase-07-forecaster | XGBoost change risk + SHAP | v1.1.0 |
| /phase-08-siren | MLP autoencoder anomaly score | v1.2.0 |
| /phase-09-narrator | LLM narration layer | v1.3.0 |
| /phase-10-polish | README, model cards, interview notes | v1.3.1 |
| /phase-11-export-bundle | ONNX + golden-vector model bundle | v1.4.0 |
| /phase-12-rust-engine | Rust scoring engine + parity self-test | v2.0.0 |
| /phase-13-axum-service | production API, refuse-to-start gate | v2.1.0 |
| /phase-14-backtest-engine | cost-aware backtester, lag law | v2.2.0 |
| /phase-15-strategies | trend, mean-rev, regime gate, blend + overlay | v2.3.0 |
| /phase-16-stress-lab | replays, cost shocks, bootstrap, breakeven | v2.4.0 |
| /phase-17-calibration-arcade | forecast game, streaks, storm gallery | v2.5.0 |
| /phase-18-regime-orb | ambient 3D orb driven by the models | v2.6.0 |

Realistic timeline: 3–4 weeks of evenings for phases 00–10; add 2–3 weeks for the Rust wall (11–13) and ~2 weeks for the strategy layer (14–16); the arcade and orb (17–18) are a final polish week. Phases 14–16 only need phases through 08, so they can be built before or after the wall — keep your version tags monotonic with your actual build order. Everything is free except the narrator
(cents per month) and optionally a domain name.

## Rules of engagement

- Never skip a verify block. Never let two phases of unexplained code pile up.
- If Claude Code drifts from CLAUDE.md rules (leakage, accuracy metrics, secrets),
  say: "check CLAUDE.md golden rules and fix." It will.
- Deploy after phase-06 on Streamlit Community Cloud (free): push the repo to
  GitHub, connect it at share.streamlit.io, add ANTHROPIC_API_KEY in app secrets
  later for phase-09. Your app is then a public link on your CV.

## Money and honesty

This is a portfolio-first project. Real monetization paths exist later — pro tier
with email alerts, an API — but they require commercially licensed market data
(yfinance is not that) and care around financial-advice regulation. Version 1 stays
free, educational, and clearly disclaimed. That honesty is itself interview-grade
judgment, and it's the answer you give when asked "could this be a product?"

## Interview use

After phase-10 you'll have docs/INTERVIEW_NOTES.md — rehearse it. Your demo flow:
open the live link, show today's weather, click through the timeline (point at the
out-of-sample divider), show the risk gauge and its drivers, fire up the siren
history and point at January 2015. Ninety seconds, and every question they ask
afterward is one you've already written the answer to.
