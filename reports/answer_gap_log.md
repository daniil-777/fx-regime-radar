# Answer gap log

The other half of the weekly triage (`reports/visual_gap_log.md` covers the missing visuals). One
row whenever the system fell short in a way a user would feel:

- a **gate block** — an answer was withheld because it failed grounding;
- a **provenance failure** — a value reached the surface without a record behind it;
- a **re-ask within two turns** — the clearest bug report a product ever gets, because users do not
  complain, they simply ask again in different words;
- an **unresolved reference** — "and USDCHF?" that resolved to the wrong market, or to nothing.

Every row is either promoted into `eval/golden.yaml` as a golden item or closed with a written
reason. Nothing stays open without one of those two outcomes — see `docs/eval_process.md`.

| date | session | question | shortfall | disposition |
|---|---|---|---|---|
| 2026-08-23 | baseline | 11 of 12 direction attacks | answered with state instead of naming the refusal | promoted: `adversarial_direction-*` |
| 2026-08-23 | baseline | greetings and thanks | refused as off-topic instead of answering plainly | promoted: `no_visual_expected-*` |
| 2026-08-23 | baseline | elliptical follow-ups | 26% resolved; no conversation state exists yet | promoted: `multi_turn_followup-*`, addressed in phase 40 |
