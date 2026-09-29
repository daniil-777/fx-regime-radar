---
description: Audit 03 — the surfaces: dashboard vs spec, honesty on screen, orb budget, accessibility floor, direction lint (audit series — tag v2.6.1 at close-out)
---

Read CLAUDE.md golden rules first. This session wears the analyst hat and
audits everything a human sees — the dashboard, the reports, the README —
against the requirements the built phases actually promised, and against the
three readers: the recruiter (three seconds, nothing wobbles), the quant (no
claim without its number), the treasurer (a decision and a disclaimer in
view). One scope law up front: the CURRENT look is the phase-05 system
(Inter + JetBrains Mono, card #131A26, border #232D3F). The token system in
CLAUDE.md's design section (nimbus/front/Space Grotesk/IBM Plex,
design/tokens.json, `make lint-ui`) is the phase-31 TARGET and is not built —
audit against what was promised through v2.6.0, and do not begin the
migration here. Prerequisite: audits 00–02 committed.

## Step 0 — confirmed repo map (sanity-check, then confirm)
Pre-filled: app/ui.py injects CSS once and owns one Plotly dark template;
pages = Overview (weather cards with regime pill, confidence bar, day count,
sparkline, change-risk gauge with top_drivers, siren dial, narration quote
with AI/auto badge), Methodology, Strategy lab (equity, drawdown, per-regime
attribution, stress panel, research banner), Arcade (call card, observatory,
storm gallery, badges), plus the orb in the hero; timeline chart with merged
regime bands and the 2017-01-01 out-of-sample divider; `st.cache_data` keyed
by file mtime, target first paint ~1 s; disclaimer footer on every page;
sidebar holds only the pair selector and disclaimer; orb discipline: ≤ 1,000
particles, pauses on document.hidden, prefers-reduced-motion collapses to
drift, WebGL failure falls back to the flat dot with zero layout shift,
added weight ≤ ~150 KB, CPU ≤ ~3% measured; README carries hero screenshot,
mermaid diagram, honest Results with the frozen scoreboard, promoted
Limitations, badges; docs/ carries model cards, INTERVIEW_NOTES, DEMO_SCRIPT;
storms.yaml entries must be `verified: true` only by hand. Verify, report
drift, WAIT.

## Requirements
A. Spec conformance walk
1. Turn the requirement lists of phases 05, 07, 08, 09, 15, 16, 17, 18 into
   one checklist and walk the running app against it item by item. Output: a
   conformance table (met / partial / missing, with file:line or screenshot
   ref). Fix inline only items that are pure display defects; anything
   touching data flow goes to the findings ledger.
2. Fresh full-page screenshots (headless) of every page into
   docs/screenshots/ with today's date in the filename; update the README
   hero if it shows a stale build.

B. Honesty on screen
3. Disclaimer audit: the rule-7 line present on every app page footer, in
   the README, and at the top of every report in reports/ — add where
   missing.
4. Direction-word lint, the golden-rule gap: add `make lint-direction` — a
   small stdlib script scanning user-facing strings (app/, README, docs/,
   reports/*.md, narrator templates) for direction and advice language
   (rise, fall, rally, drop, bullish, bearish, buy, sell, target, "you
   should", "we recommend" — case-insensitive, word-boundary, with an
   allowlist file for legitimate uses such as "falls back"). Wire it into
   `make lint` and CI. Expected outcome: a handful of hits in prose; fix
   each by rephrasing to condition language.
5. Number provenance spot-check: pick five numbers visible in the app or
   README (a PR-AUC, a Brier, a breakeven multiplier, a siren percentile, a
   strategy Sharpe) and trace each to its artifact cell or report line;
   any orphan number is a finding. Model cards' versions must match the
   files in models/ exactly; CHANGELOG is complete v0.1.0 → v2.6.0 with
   dates.
6. Narration audit: read today's report.json against its stats dict field
   by field — three sentences, zero invented facts, badge shows the true
   source. Verify the arcade's pre-lock payload really lacks the model
   value (inspect the rendered payload, not the code comment).

C. Performance and motion budget
7. Time every loader and the first paint; record numbers in STATE.md;
   confirm caches key on file mtime and no model imports occur in app code.
8. Orb measurements, recorded not asserted: particle count from the JS,
   CPU % on this machine, added page weight in KB, reduced-motion behavior,
   hidden-tab pause, and the WebGL-failure fallback (force it) with zero
   layout shift. Any budget miss is fixed if display-only, flagged
   otherwise. Confirm the JS preset object still mirrors the Python palette
   dict exactly (the documented easy-to-forget pair).

D. Accessibility floor (current palette)
9. Compute contrast ratios (stdlib script) for every text/surface pair in
   use; table in the session; fix any text below 4.5:1 by adjusting TONE
   only — never a regime hue's meaning, and no early adoption of phase-31
   colors. Regime is never color-only: word + dot everywhere a color
   appears. Touch targets ≥ 44 px; keyboard focus visible on interactive
   elements; note Streamlit-imposed limits honestly where they bind.

E. Failure states
10. Simulate a failed data fetch and confirm the app serves last-good
    artifacts with the "data through" date; confirm error copy says what
    happened and what to do next — never apologizes, never vague. Empty and
    stale states for the arcade (no calls yet) and Strategy lab render
    deliberately, not as blank panels.

## Do not
No redesign, no phase-31 token migration, no new chart types, no third
animation, no new features, no emoji as UI. No screenshot retouching — the
app must earn the image. No weakening the research banner or any
disclaimer. No touching model or pipeline code.

## Verify
- Conformance table and contrast table read to me; screenshots shown;
  loader timings and orb numbers recorded in STATE.md.
- `make lint-direction` green after rephrasing, and wired into `make lint`
  and CI.
- The five-number provenance trace shown.
- CHANGELOG; commit `audit-03: surfaces audit (+lint-direction)`. No tag.

## Teach me
Explain: why the direction lint guards a legal posture and not just a style
preference, and why "adjust tone, never meaning" is the right rule when a
regime color fails contrast. Then quiz me: (1) a recruiter's three-second
glance lands on the Overview screenshot — name the two most likely things
to wobble and how this session prevented each; (2) why is a stale
screenshot in the README worse than no screenshot? Critique my answers.
