---
description: Phase 10 — polish, documentation, and interview pack (v1.3.1)
---

Read CLAUDE.md one more time. This phase turns a working app into a hiring
asset. Nothing new gets built; everything gets finished.

## Task
Professional README, model cards, interview notes, demo script, and a clean
final pass over code quality.

## Requirements
1. README rewrite, in this order: hero screenshot; one-paragraph pitch; live
   app link placeholder; a mermaid architecture diagram matching CLAUDE.md's
   pipeline; "How it works" in plain English (regimes → change risk → siren →
   narration); an honest Results section with the frozen test-set scoreboard
   from phase-07 and one calibration plot; Limitations (promoted, not hidden);
   Repo tour; Run locally; the disclaimer. Badges: CI status and "data updated
   daily".
2. `docs/model_cards.md`: one card per model (HMM, forecaster, siren) —
   purpose, data, features, training window, eval, known failure modes,
   version.
3. `docs/INTERVIEW_NOTES.md`: crisp written answers, in the developer's voice,
   to: why HMM over k-means; filtered vs smoothed; how leakage is prevented
   (name the tests); why the embargo; why not accuracy; what calibration means;
   why the neural net is tiny and why no from-scratch transformer on this data
   size; how the LLM is prevented from hallucinating; what you would build
   next with more time and data. Add a "hard question" for each with a
   suggested response.
4. `docs/DEMO_SCRIPT.md`: a 90-second walkthrough script — weather cards, the
   timeline with the out-of-sample divider, the risk gauge and its drivers,
   the siren spiking on 2015-01-15 — ending with the one-sentence pitch:
   three ML paradigms, correctly matched to three problems, no price
   prediction anywhere.
5. Code pass: ruff and black clean; type hints on all public functions; test
   run summary in the README; CHANGELOG complete from v0.1.0 with dates;
   remove dead code and stray files.
6. Final commit `phase-10: polish`, tag `v1.3.1`. Print my launch checklist:
   push, confirm Action ran green, confirm the live app updated, add the live
   link and screenshot to the README, then put the link on my CV and LinkedIn.

## Do not
No new features. No overclaiming in the README — the Results paragraph uses
the measured numbers, whatever they are.

## Verify
- Read me the final README top to bottom as a skeptical hiring manager and fix
  what stumbles. Show `make lint` and `make test` green, and the tag list.

## Teach me
Quiz me from INTERVIEW_NOTES.md: ask me five of the questions cold, one at a
time, and grade my spoken-style answers with specific fixes. This rehearsal is
the phase's real deliverable.
