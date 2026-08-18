---
description: Phase 09 — LLM narration layer with guardrails and fallback (v1.3.0)
---

Read CLAUDE.md golden rules 4 and 9. Build `src/fxradar/narrate.py`.

## Task
Turn each pair's computed numbers into a three-sentence plain-English daily
report via the Anthropic API, with a deterministic fallback, and surface it in
the app.

## Requirements
1. `build_stats(pair) -> dict` from regimes.parquet: regime, regime_prob,
   days_in_regime, change_risk_5d, top_drivers, anomaly_pct, nearest-neighbor
   date, plus 5-day return. Numbers only — no free text goes in.
2. `narrate(stats) -> str` using the anthropic SDK. Check Anthropic's current
   model list in the docs and use the latest small Haiku-class model
   (e.g. "claude-haiku-4-5" — verify the exact string), temperature 0.3,
   max_tokens 350. System prompt, verbatim:
   "You are the narrator for an educational FX dashboard. Using ONLY the JSON
   provided, write exactly three sentences in calm, plain English: (1) the
   current regime, its confidence and age; (2) the 5-day regime-change risk
   and its top drivers, translated into ordinary words; (3) the anomaly
   status, mentioning the closest historical match only if anomaly_pct > 90.
   Never predict prices, never give advice, never add facts not present in
   the JSON, never use jargon without a plain-word gloss."
3. Robustness: read the key from env or Streamlit secrets; 2 retries with
   backoff; on any failure or missing key, fall back to
   `template_narrate(stats)` — a deterministic f-string version of the same
   three sentences. Output `data/report.json` per the contract with
   source: "llm" or "template".
4. Register in run_daily.py AFTER all scoring. In CI the key is absent by
   design this phase — the pipeline must succeed via template. Document adding
   ANTHROPIC_API_KEY to GitHub and Streamlit secrets for live narration, and
   add a one-line daily cost estimate to the README (it is cents per month).
5. Dashboard: narration paragraph on each weather card in a quote style, with
   a tiny source badge (AI or auto) and generated_at timestamp.
6. Tests (no network): template path produces exactly three sentences
   containing the regime name and the risk figure; missing-key path never
   raises; a mocked-client test asserts the request contains the system prompt
   and only JSON-derived user content.

## Do not
No market knowledge from the model's memory. No key in code, git, or logs.
No blocking API calls inside the Streamlit app — narration is read from the
artifact only.

## Verify
- Pipeline run without a key → report.json with source template, shown.
- With my key set locally → source llm, text shown; confirm three sentences
  and zero invented facts against the stats dict, line by line.
- `make test` green. CHANGELOG, commit `phase-09: narrator`, tag `v1.3.0`.

## Teach me
Explain: why "narrates computed numbers only" kills hallucination risk, and why
the fallback makes the system production-grade. Two interview questions about
safe LLM integration; critique my answers.
