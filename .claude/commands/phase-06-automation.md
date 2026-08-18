---
description: Phase 06 — daily pipeline, GitHub Actions, and deployment (v1.0.1)
---

Read CLAUDE.md architecture and golden rules 8–9. Make the app self-updating.

## Task
Build `pipelines/run_daily.py` as the single orchestrator, wire it into a
scheduled GitHub Action that commits fresh artifacts, and prepare deployment.

## Requirements
1. `run_daily.py`: data → features → HMM scoring (LOAD the saved models — never
   refit here) → write artifacts. Idempotent: safe to run twice a day. Clear
   stage logging with timings; nonzero exit on any stage failure. Structure it
   so phases 07–09 can register their scoring steps with one line each.
2. `.github/workflows/daily.yml`: cron for weekdays 06:00 UTC plus
   workflow_dispatch for manual runs; checkout, setup Python 3.11 with pip
   cache, install requirements, run the pipeline, then commit and push changed
   files under data/ with message "data: daily refresh [skip ci]".
   `permissions: contents: write`. Keep total runtime under ~5 minutes.
3. A refit workflow or documented manual path for monthly model refits
   (expanding train window per CLAUDE.md rules), bumping model_version.
4. README section "Deploy": push to GitHub, create the app on Streamlit
   Community Cloud pointing at app/app.py, note that ANTHROPIC_API_KEY gets
   added to app secrets in phase-09. Add a "last updated" caption in the app
   sourced from the artifact, so freshness is visible to visitors.
5. Failure honesty: if today's data fetch fails, the pipeline exits nonzero,
   artifacts stay at the last good state, and the app keeps showing them with
   its "data through" date — verify this path by simulating a fetch failure.

## Do not
No secrets in the workflow file. No model training in the daily job. No
force-pushes.

## Verify
- Local `make pipeline` end-to-end run shown with stage timings.
- Show me the workflow file and dry-run reasoning line by line; validate YAML.
- Simulated-failure behavior demonstrated. CHANGELOG, commit
  `phase-06: automation`, tag `v1.0.1`. Then I will push and deploy — give me
  the exact click-path checklist.

## Teach me
Explain: why score daily but refit monthly, and what idempotent means with a
concrete example from this pipeline. Two interview questions about ML ops for
small systems; critique my answers.
