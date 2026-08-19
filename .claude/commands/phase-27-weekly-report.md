---
description: Phase 27 — weekly FX weather report + public metrics page (next minor tag)
---

Read CLAUDE.md golden rules first. The lead-generation engine: one useful
page every Monday, free forever, plus the five numbers investors ask about.

## Step 0 — confirmed repo map (sanity-check, then confirm)
Pre-filled: `build_stats()` and `template_narrate()` exist in
src/fxradar/narrate.py (deterministic, three sentences, no LLM required);
the daily Action commits artifacts; the app deploys on Streamlit Community
Cloud, so static pages publish from the repo (docs/ + GitHub Pages).
Verify, report drift, WAIT.

## Task
An auto-generated Monday report (markdown + email-safe HTML + RSS) reusing
the narrator's template path, and a public metrics page.

## Requirements
1. `src/fxradar/weekly.py`: per pair — regime, change risk ± interval,
   anomaly_pct, generic traffic-light summary (never personalized), days to
   next SNB/ECB/Fed/BoE events, one template_narrate-style paragraph, link
   to the proof page. Deterministic given artifacts.
2. Outputs: `docs/weekly/YYYY-MM-DD.md`, an email-safe light-mode HTML
   variant, and `docs/feed.xml` (RSS). A Monday step in the existing
   workflow (or a second cron) generates and commits them. Zero paid
   services; leave a documented hook for an email provider later.
3. Metrics page (app page + a README table): ledger days live, report
   subscribers, active API keys, design partners, MRR — auto where possible,
   honest zeros otherwise.
4. Direction-language lint on all templates; mobile rendering checked; the
   ops log records "report published" so a silent Monday is visible.

## Do not
No personalized advice; weekly only; no paid services; no subscriber data
without a privacy note; no direction language.

## Verify
- Generate this Monday's report from real artifacts; show md, HTML email,
  RSS, and a mobile screenshot; metrics page live with honest numbers.
- Lint + `make test` green. CHANGELOG, commit `phase-27: weekly report`,
  next minor tag.

## Teach me
Why a free weekly artifact beats ads for this buyer; what open rate and
forwarding tell an investor. Quiz: (1) why generic, not personalized,
traffic lights here? (2) which metric would you fake last, and why is that
the one that matters? Critique my answers.
